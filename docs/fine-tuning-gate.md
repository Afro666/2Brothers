# Nemotron fine-tuning gate (#364)

Decision recorded 2026-11-14, before the Saturday 14:00 gate: **no-go for
training in this demo round**. Continue the prompt/benchmark improvement in
#365. No adapter has been trained or served, and no fine-tuning gain is claimed.

The issue explicitly permits completion with a note explaining why training
was dropped. We are taking that exit early rather than scheduling a paid job
without an agreed budget. There is no approved training-node budget, validated
recipe for this exact checkpoint, frozen SFT training/held-out seed split, or
running training job in the implementation reviewed for this issue. The
approval-to-order demo and recall enforcement take priority.

NVIDIA publishes a [BF16 checkpoint](https://huggingface.co/nvidia/NVIDIA-Nemotron-3.5-Super-VL-120B-A12B-BF16)
for customization. Its card describes a hybrid 120B-parameter model with 12B
active parameters. The deployment examples are inference configurations; they
do not establish the training capacity or price required for our LoRA job.
The issue's proposed GPU count is therefore an unvalidated planning estimate.
The shared inference endpoint cannot substitute for a training worker.

Reopen as a separately budgeted experiment only after an owner has:

- Agreed a GPU-hour/spend cap and verified node availability and the exact
  model's training/adapter-serving compatibility.
- Frozen training and held-out seeds and generated reproducible reference
  observation/action pairs without held-out leakage.
- Run a small training smoke test and retained loss, token and cost logs.
- Specified paired base/adapter evaluation on identical seeds, including
  invalid actions, service failures and ordering safety, as well as score.

The proposed comparison must retain the same scoring version and report
uncertainty across seeds. Existing benchmark figures are baseline evidence,
not evidence of an adapter improvement. #279 must remain independent of this
experiment.
