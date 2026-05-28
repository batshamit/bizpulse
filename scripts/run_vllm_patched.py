#!/usr/bin/env python3
"""
Wrapper script for vLLM to apply the torch.library.custom_op monkeypatch
before importing transformers, preventing schema inference errors.
"""

import runpy

# Apply the torch.library.custom_op monkeypatch
try:
    import torch.library

    _orig_custom_op = torch.library.custom_op

    def my_custom_op(name, fn=None, **kwargs):
        if name == "transformers::grouped_mm_fallback" and fn is not None:
            import torch

            # Convert string annotations to actual torch.Tensor types
            fn.__annotations__ = {
                k: (torch.Tensor if v == "torch.Tensor" else v)
                for k, v in fn.__annotations__.items()
            }
        return _orig_custom_op(name, fn, **kwargs)

    torch.library.custom_op = my_custom_op
    print("Successfully applied torch.library.custom_op monkeypatch.")
except Exception as e:
    print(f"Warning: Could not apply custom_op monkeypatch ({e}). Continuing anyway.")

# Run the original vLLM entrypoint module as __main__
if __name__ == "__main__":
    runpy.run_module("vllm.entrypoints.openai.api_server", run_name="__main__")
