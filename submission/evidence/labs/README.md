# Mandatory labs: completed on our IBM LinuxONE server

Both labs from the LinuxONE Community Cloud
[jupyter-lab-ml](https://github.com/linuxone-community-cloud/jupyter-lab-ml) guide were run end to
end on **our team VM** (`rescueflow`, Ubuntu 24.04, **s390x**, AI_LAB flavor: 3 cores / 8 GB) inside
IBM's official container image `registry.linuxone.cloud.marist.edu/l1cc/jupyterlab-image-s390x`.

| Lab | Notebook | Executed | Errors | Run on |
|---|---|---|---|---|
| **1. Hybrid multi-model** | `Churn_Scikit_PyTorch.ipynb` | 31 / 31 code cells | 0 | 2026-10-17 20:57–21:00 UTC, s390x |
| **2. Predictive + generative AI** | `Loan_Approval_Demo.ipynb` | 9 / 9 code cells | 0 | 2026-10-17 21:00–21:02 UTC, s390x |

Files in this folder (open the `.html` files in a browser to see every cell, output and chart):

- `Churn_Scikit_PyTorch_executed_s390x.ipynb` / `.html`
- `Loan_Approval_Demo_executed_s390x.ipynb` / `.html`

---

## Lab 1: Hybrid multi-model (client retention)

Two different model families on the same problem, trained and scored on LinuxONE:

- **Data:** 6,001 bank clients and 20,000 credit-card transactions, joined in pandas into per-client
  features (transaction counts, amounts, daily activity), with exploratory charts and a correlation
  matrix.
- **Model A, scikit-learn Random Forest:** predicts churn, estimates lost revenue per client and by
  age group, and is **exported to PMML** (portable model format).
- **Model B, PyTorch logistic regression:** churn from activity level, age, income and investments,
  with class weighting (`pos_weight = 2.91`). After 300 epochs: **train accuracy 74.9%, test
  accuracy 73.4%** (1,201 test clients).

## Lab 2: Predictive + generative AI (loan decisioning)

A hybrid pipeline: a classic ML model makes the decision, and an LLM reads documents and explains
the result.

- **Generative model:** IBM **Granite 4.0** (350M, big-endian GGUF for s390x, the model shipped in
  the container; the notebook text mentions Granite 3.3 2B) served by **llama.cpp 0.3.36**. The
  container reports llama.cpp build flags `-DGGML_ZDNN=ON` (IBM zDNN / NNPA backend),
  `-DGGML_BLAS=ON` (OpenBLAS on the z vector unit) and `-march=z16`. The zDNN backend is real
  (`libggml-zdnn.so`, 23 KB, linked against IBM's `libzdnn.so.0`; the notebook prints it as
  "0.0 MB" because of rounding), and our VM's CPU exposes the NNPA accelerator. The run's logs do
  **not** show which device executed the inference, so we do not claim the Granite inference ran on
  NNPA.
- **Step 1, read documents (generative):** Granite extracts features from the applicant's bank
  statement, paystub and W-2:
  > Financial Stability: High · Cash Flow Stability: High · Income Consistency: High · Compliance
  > Status: Compliant
- **Step 2, score risk (predictive):** an **XGBoost** model: `Low Risk`, probability 0.997.
- **Step 3, retrieve policy (RAG):** BM25 search over the lending policy documents.
- **Step 4, recommend (generative):**
  > **Recommendation: Approve.** Main reason: high credit score, low DTI and stable documented
  > income meet policy.
- **Step 5, answer questions (generative):**
  > The applicant has a high credit score and strong income relative to the loan amount. Documents
  > show positive cash flow, consistent income and compliance, and the risk model predicts low risk.

---

## How these labs map to RescueNYC

RescueNYC follows the same two patterns, applied to NYC EMS dispatch:

| Lab pattern | In RescueNYC |
|---|---|
| Hybrid multi-model | Gradient-boosted trees (XGBoost) compared with logistic regression and rule baselines on the same task, all trained and evaluated on the VM |
| Predictive + generative | The XGBoost stress risk feeds an operator briefing (template, optionally a local Granite model via llama.cpp), and a verifier rejects any number the model did not produce |

## Reproduce

On the VM (rootless Podman, no sudo needed once the image is pulled):

```bash
podman pull registry.linuxone.cloud.marist.edu/l1cc/jupyterlab-image-s390x:latest
mkdir -p ~/labs
for nb in Churn_Scikit_PyTorch Loan_Approval_Demo; do
  podman run --rm --userns=keep-id -v $HOME/labs:/home/ibm-user/out:Z \
    --entrypoint sh registry.linuxone.cloud.marist.edu/l1cc/jupyterlab-image-s390x:latest -c \
    "cd /home/ibm-user && jupyter nbconvert --to notebook --execute --output-dir out \
       --output ${nb}_executed_s390x $nb.ipynb && \
     jupyter nbconvert --to html --output-dir out out/${nb}_executed_s390x.ipynb"
done
```

For the interactive version (as in the guide), start the container on port 38888 and open it through
an SSH tunnel (`ssh -L 38888:localhost:38888 linux1@<vm-ip>`), so the default Jupyter token is never
exposed to the internet.
