
import torch
from collections import namedtuple

from rlpyt.algos.base import RlAlgorithm
from rlpyt.algos.utils import (discount_return, generalized_advantage_estimation,
    valid_from_done)
from rlpyt.algos.utils import (discount_return_tl,
    generalized_advantage_estimation_tl)

# Convention: traj_info fields CamelCase, opt_info fields lowerCamelCase
OptInfo = namedtuple("OptInfo", ["loss", "gradNorm", "entropy", "perplexity"])
AgentTrain = namedtuple("AgentTrain", ["dist_info", "value"])


class PolicyGradientAlgo(RlAlgorithm):

    bootstrap_value = True
    opt_info_fields = tuple(f for f in OptInfo._fields)  # copy

    def initialize(self, agent, n_itr, batch_spec, mid_batch_reset=False,
            examples=None, world_size=1, rank=0):
        """Params batch_spec and examples unused."""
        self.optimizer = self.OptimCls(agent.parameters(),
            lr=self.learning_rate, **self.optim_kwargs)
        if self.initial_optim_state_dict is not None:
            self.optimizer.load_state_dict(self.initial_optim_state_dict)
        self.agent = agent
        self.n_itr = n_itr
        self.batch_spec = batch_spec
        self.mid_batch_reset = mid_batch_reset

    def process_returns(self, samples):
        reward, done, value, bv = (samples.env.reward, samples.env.done,
            samples.agent.agent_info.value, samples.agent.bootstrap_value)
        done = done.type(reward.dtype)
        if self.bootstrap_timelimit:
            timeout = samples.env.env_info.timeout
            if self.gae_lambda == 1:
                return_ = discount_return_tl(reward, done, bv, self.discount,
                    timeout=timeout, value=value)
                advantage = return_ - value
            else:
                advantage, return_ = generalized_advantage_estimation_tl(
                    reward, value, done, bv, self.discount, self.gae_lambda,
                    timeout=timeout)
        else:
            if self.gae_lambda == 1:  # GAE reduces to empirical discounted.
                return_ = discount_return(reward, done, bv, self.discount)
                advantage = return_ - value
            else:
                advantage, return_ = generalized_advantage_estimation(
                    reward, value, done, bv, self.discount, self.gae_lambda)

        if not self.mid_batch_reset or self.agent.recurrent:
            valid = valid_from_done(done)  # Recurrent: no reset during training.
        else:
            valid = torch.ones_like(done) if self.bootstrap_timelimit else None
        if self.bootstrap_timelimit:
            # Turn OFF training on 'done' samples due to timeout, because no valid
            # next_state for bootstrap_value(next_state).
            valid *= (1 - samples.env.env_info.timeout.float())

        if self.normalize_advantage:
            if valid is not None:
                valid_mask = valid > 0
                adv_mean = advantage[valid_mask].mean()
                adv_std = advantage[valid_mask].std()
            else:
                adv_mean = advantage.mean()
                adv_std = advantage.std()
            advantage[:] = (advantage - adv_mean) / max(adv_std, 1e-6)

        return return_, advantage, valid
