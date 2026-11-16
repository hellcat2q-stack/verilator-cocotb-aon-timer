"""Use the frozen bus/clock replay test with an isolated repaired-reference adapter."""
import test_uvm_sample_replay as frozen_replay
from pinned_sampling_fixed_adapter import PinnedSamplingFixedAdapterV1

frozen_replay.CocotbCoverageAdapter = PinnedSamplingFixedAdapterV1
replay_uvm_accepted_stimulus = frozen_replay.replay_uvm_accepted_stimulus
