#!/usr/bin/env python3
"""
TEI Server Replica for BizPulse.
Serves embeddings or reranker models using FastAPI and PyTorch/Transformers.
Designed to run on a selected GPU to avoid Docker container dependencies.
"""

import argparse
import os
import sys

# Apply PyTorch/transformers schema inference monkeypatch
try:
    import torch.library

    _orig_custom_op = torch.library.custom_op

    def my_custom_op(name, fn=None, **kwargs):
        if name == "transformers::grouped_mm_fallback" and fn is not None:
            import torch

            fn.__annotations__ = {
                k: (torch.Tensor if v == "torch.Tensor" else v)
                for k, v in fn.__annotations__.items()
            }
        return _orig_custom_op(name, fn, **kwargs)

    torch.library.custom_op = my_custom_op
except Exception:
    pass

# Ensure dependencies are available before importing FastAPI/PyTorch
try:
    import torch
    import uvicorn
    from fastapi import FastAPI
    from pydantic import BaseModel
    from transformers import AutoModel, AutoModelForSequenceClassification, AutoTokenizer
except ImportError as e:
    print(
        f"Error: Missing required dependency for TEI Server ({e}). Please ensure you are in the active environment.",
        file=sys.stderr,
    )
    sys.exit(1)

app = FastAPI(title="TEI Server Replica")

# Global variables for models
tokenizer = None
model = None
task_type = None
device = "cuda" if torch.cuda.is_available() else "cpu"


# --- Request/Response Models ---
class EmbedRequest(BaseModel):
    inputs: list[str]


class RerankRequest(BaseModel):
    query: str
    texts: list[str]
    top_n: int | None = None


# --- Endpoints ---
@app.get("/health")
async def health():
    return {"status": "healthy"}


@app.post("/embed")
async def embed(req: EmbedRequest):
    if task_type != "embed":
        return {"error": "Server is configured for reranking, not embeddings."}, 400

    if not req.inputs:
        return []

    with torch.no_grad():
        inputs = tokenizer(
            req.inputs, padding=True, truncation=True, return_tensors="pt", max_length=512
        )
        inputs = {k: v.to(device) for k, v in inputs.items()}
        outputs = model(**inputs)
        # Use L2-normalized [CLS] token representation for BGE embeddings
        embeddings = outputs[0][:, 0]
        embeddings = torch.nn.functional.normalize(embeddings, p=2, dim=1)
        return embeddings.cpu().tolist()


@app.post("/rerank")
async def rerank(req: RerankRequest):
    if task_type != "rerank":
        return {"error": "Server is configured for embeddings, not reranking."}, 400

    if not req.texts:
        return []

    pairs = [[req.query, doc] for doc in req.texts]
    with torch.no_grad():
        inputs = tokenizer(
            pairs, padding=True, truncation=True, return_tensors="pt", max_length=512
        )
        inputs = {k: v.to(device) for k, v in inputs.items()}
        outputs = model(**inputs)
        logits = outputs.logits.view(-1).float()
        # Scale scores using sigmoid to be strictly between 0 and 1
        scores = torch.sigmoid(logits).cpu().tolist()

    results = [{"index": i, "score": scores[i]} for i in range(len(req.texts))]
    results.sort(key=lambda x: x["score"], reverse=True)
    if req.top_n is not None:
        results = results[: req.top_n]
    return results


def main():
    global tokenizer, model, task_type

    parser = argparse.ArgumentParser(description="TEI Server Replica (Embeddings/Reranker)")
    parser.add_argument(
        "--task",
        choices=["embed", "rerank"],
        required=True,
        help="Whether to run the embedding or reranking task.",
    )
    parser.add_argument("--port", type=int, required=True, help="Port to run the server on.")
    parser.add_argument("--host", default="127.0.0.1", help="Host address to bind to.")
    parser.add_argument("--model-id", help="Hugging Face Model ID to use.")

    args = parser.parse_args()
    task_type = args.task

    # Set HuggingFace Hub transfer to fast mode
    os.environ["HF_HUB_ENABLE_HF_TRANSFER"] = "1"

    # Select model based on task
    if task_type == "embed":
        model_id = args.model_id or os.environ.get("EMBED_MODEL") or "BAAI/bge-large-en-v1.5"
        print(f"Loading embedding model: {model_id} on {device}...")
        tokenizer = AutoTokenizer.from_pretrained(model_id)
        model = AutoModel.from_pretrained(model_id).to(device)
    else:
        model_id = args.model_id or os.environ.get("RERANK_MODEL") or "BAAI/bge-reranker-v2-m3"
        print(f"Loading reranker model: {model_id} on {device}...")
        tokenizer = AutoTokenizer.from_pretrained(model_id)
        model = AutoModelForSequenceClassification.from_pretrained(model_id).to(device)

    model.eval()
    print(f"Server starting on {args.host}:{args.port}...")
    uvicorn.run(app, host=args.host, port=args.port)


if __name__ == "__main__":
    main()
