#!/usr/bin/env python3
import argparse
import os
import sys

# Compatibility patch for torch.distributed.tensor.device_mesh in PyTorch 2.4+
try:
    from torch.distributed import device_mesh

    sys.modules["torch.distributed.tensor.device_mesh"] = device_mesh
except ImportError:
    pass

import torch

# Compatibility patch for missing set_submodule on nn.Module in some PyTorch builds
if not hasattr(torch.nn.Module, "set_submodule"):

    def _set_submodule(self, target: str, module: torch.nn.Module) -> None:
        atoms = target.split(".")
        name = atoms.pop(-1)
        mod = self
        for item in atoms:
            mod = getattr(mod, item)
        setattr(mod, name, module)

    torch.nn.Module.set_submodule = _set_submodule
from datasets import load_dataset
from peft import LoraConfig, get_peft_model, prepare_model_for_kbit_training
from transformers import (
    AutoModelForCausalLM,
    AutoTokenizer,
    BitsAndBytesConfig,
    set_seed,
)
from trl import SFTConfig, SFTTrainer


def parse_args():
    parser = argparse.ArgumentParser(description="BizPulse Model Fine-Tuning Script")
    parser.add_argument("--model_id", type=str, required=True, help="Hugging Face Model ID or path")
    parser.add_argument(
        "--dataset_path", type=str, required=True, help="Path to JSON/JSONL training dataset"
    )
    parser.add_argument("--context_length", type=int, default=4096, help="Maximum sequence length")
    parser.add_argument("--epochs", type=int, default=3, help="Number of training epochs")
    parser.add_argument("--batch_size", type=int, default=1, help="Micro-batch size per GPU")
    parser.add_argument(
        "--gradient_accumulation_steps", type=int, default=4, help="Gradient accumulation steps"
    )
    parser.add_argument("--lr", type=float, default=2e-5, help="Learning rate")
    parser.add_argument(
        "--output_dir",
        type=str,
        default="outputs/bizpulse_model",
        help="Directory to save final model",
    )
    parser.add_argument("--use_qlora", action="store_true", help="Enable 4-bit QLoRA quantization")
    parser.add_argument("--lora_r", type=int, default=16, help="LoRA rank dimension")
    parser.add_argument("--lora_alpha", type=int, default=32, help="LoRA alpha scaling parameter")
    parser.add_argument("--lora_dropout", type=float, default=0.05, help="LoRA dropout rate")
    parser.add_argument("--deepspeed", type=str, default=None, help="Path to DeepSpeed config JSON")
    parser.add_argument(
        "--local_rank", type=int, default=-1, help="Local rank for distributed training"
    )
    return parser.parse_args()


def main():
    args = parse_args()
    set_seed(42)

    # Determine if running under distributed execution (DeepSpeed / PyTorch DDP)
    is_distributed = args.local_rank != -1 or "LOCAL_RANK" in os.environ
    local_rank = int(os.environ.get("LOCAL_RANK", args.local_rank))

    if is_distributed:
        torch.cuda.set_device(local_rank)
        device_map = None  # DeepSpeed manages model placement/sharding
    else:
        device_map = "auto"

    print(f"Loading tokenizer: {args.model_id}")
    tokenizer = AutoTokenizer.from_pretrained(args.model_id, trust_remote_code=True)
    if tokenizer.pad_token is None:
        tokenizer.pad_token = tokenizer.eos_token
        tokenizer.pad_token_id = tokenizer.eos_token_id

    # Configure quantization (QLoRA) if requested
    quant_config = None
    if args.use_qlora:
        print("QLoRA 4-bit quantization enabled.")
        quant_config = BitsAndBytesConfig(
            load_in_4bit=True,
            bnb_4bit_quant_type="nf4",
            bnb_4bit_use_double_quant=True,
            bnb_4bit_compute_dtype=torch.float16,  # Must be float16 for V100 GPUs
        )

    print(f"Loading model: {args.model_id}")
    # Scaled Dot Product Attention (SDPA) is used for Volta/V100 optimization
    model = AutoModelForCausalLM.from_pretrained(
        args.model_id,
        quantization_config=quant_config,
        device_map=device_map,
        torch_dtype=torch.float16,
        attn_implementation="sdpa",
        trust_remote_code=True,
    )

    if args.use_qlora:
        model = prepare_model_for_kbit_training(model, use_gradient_checkpointing=True)

    # Target standard projection modules for training
    target_modules = ["q_proj", "v_proj", "k_proj", "o_proj", "gate_proj", "up_proj", "down_proj"]
    peft_config = LoraConfig(
        r=args.lora_r,
        lora_alpha=args.lora_alpha,
        lora_dropout=args.lora_dropout,
        target_modules=target_modules,
        bias="none",
        task_type="CAUSAL_LM",
    )

    model = get_peft_model(model, peft_config)
    model.print_trainable_parameters()

    # Load dataset
    print(f"Loading dataset from: {args.dataset_path}")
    dataset = load_dataset("json", data_files=args.dataset_path)

    # Setup prompt formatting function
    def format_prompts(example):
        inst = example["instruction"]
        resp = example["response"]
        return f"<|im_start|>user\n{inst}<|im_end|>\n<|im_start|>assistant\n{resp}<|im_end|>"

    # Configuration for training args
    training_args = SFTConfig(
        output_dir=args.output_dir,
        num_train_epochs=args.epochs,
        per_device_train_batch_size=args.batch_size,
        gradient_accumulation_steps=args.gradient_accumulation_steps,
        learning_rate=args.lr,
        logging_steps=10,
        save_strategy="epoch",
        eval_strategy="no",
        fp16=True,  # Strictly use FP16 (V100 compatibility)
        bf16=False,
        deepspeed=args.deepspeed,
        local_rank=args.local_rank,
        gradient_checkpointing=True,
        report_to="none",
        remove_unused_columns=False,
        max_length=args.context_length,
        packing=True,
    )

    trainer = SFTTrainer(
        model=model,
        train_dataset=dataset["train"],
        formatting_func=format_prompts,
        processing_class=tokenizer,
        args=training_args,
    )

    print("Starting training loop...")
    trainer.train()

    print(f"Saving fine-tuned adapter to: {args.output_dir}")
    trainer.model.save_pretrained(args.output_dir)
    tokenizer.save_pretrained(args.output_dir)
    print("Training successfully complete!")


if __name__ == "__main__":
    main()
