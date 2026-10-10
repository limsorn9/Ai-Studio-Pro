"""Lean, Gradio-compatible VoxCPM2 inference server for Dubber Bisach.

The upstream demo is intentionally feature rich: it loads an ASR stack and a denoiser and rebuilds
reference-audio features for every click.  The desktop application already owns transcription,
normalization, validation, and the UI, so its sidecar only needs synthesis.  Keeping this adapter in
the application also gives managed installations a stable wire contract while VoxCPM's demo evolves.

Beyond the wire contract, this file is where the model is made to fit the machines it actually runs
on.  Upstream assumes a datacenter card; the customers' laptops have six cores and, at best, a 4 GB
GPU.  Three adaptations live here, each guarded so that an upstream change degrades to the stock
behaviour rather than to a wrong answer:

- **Sliced attention.**  Upstream attends over every slot of its 8192-entry static KV cache on every
  autoregressive step, masked rather than sliced.  On a CPU without bfloat16 hardware that is the
  single largest cost per step.  ``_install_sliced_attention`` trims the window to the tokens that
  exist.
- **Hybrid placement.**  The two language models (82 % of the weights) stay on the CPU while the
  acoustic stack — feature encoder, diffusion decoder, audio VAE — runs on a small GPU.  About 1.3 GB
  of VRAM instead of 5.3 GB.  ``VoxCPM2Hybrid`` overrides the three methods that cross the seam.
- **Float32 language models** on CPUs without AVX512-BF16, where bfloat16 matmuls are emulated.
- **Float16 acoustic stack** on GPUs without bfloat16 tensor cores (Turing: GTX 16 / RTX 20), where
  bfloat16 runs through a slow emulation path.  ``_acoustic_dtype_for`` reads the compute capability.
"""

from __future__ import annotations

import argparse
import ctypes
import hashlib
import importlib.util
import inspect
import json
import logging
import os
import re
import sys
import threading
from collections import OrderedDict
from pathlib import Path
from threading import Lock
from typing import Optional

import gradio as gr
import numpy as np
import torch
import voxcpm
from voxcpm.model.utils import resolve_runtime_device


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)
logger = logging.getLogger("dubber-bisach-voxcpm2")
os.environ.setdefault("TOKENIZERS_PARALLELISM", "false")


def _positive_int(name: str, default: int, maximum: int) -> int:
    try:
        value = int(os.environ.get(name, str(default)))
    except ValueError:
        value = default
    return max(1, min(maximum, value))


# --------------------------------------------------------------------------------------------- #
# Process hygiene: die with the parent, stay out of the foreground's way, use the threads we are given
# --------------------------------------------------------------------------------------------- #


def _install_parent_watchdog(parent_pid: int) -> None:
    """Exit when the Electron process that launched us is gone.

    A crash of the desktop app used to leave this process — and 4.3 GB of weights — resident until
    the next reboot, on a port the next launch would then find occupied.  On Windows the wait is a
    kernel handle, so it costs nothing until it fires; elsewhere a poll every two seconds does.
    """

    def _exit() -> None:
        logger.info("Parent process %d has exited; shutting down.", parent_pid)
        os._exit(0)

    if sys.platform == "win32":
        SYNCHRONIZE = 0x00100000
        handle = ctypes.windll.kernel32.OpenProcess(SYNCHRONIZE, False, parent_pid)
        if not handle:
            logger.warning("Could not open parent process %d; no watchdog.", parent_pid)
            return

        def _wait() -> None:
            ctypes.windll.kernel32.WaitForSingleObject(handle, 0xFFFFFFFF)
            _exit()
    else:
        import time

        def _wait() -> None:
            while True:
                try:
                    os.kill(parent_pid, 0)
                except OSError:
                    _exit()
                time.sleep(2)

    threading.Thread(target=_wait, name="parent-watchdog", daemon=True).start()


def _lower_process_priority() -> None:
    """Below-normal priority: the editor stays responsive while every core is busy.

    This does not slow the work when nothing else wants the CPU; it only decides who wins when the
    customer drags the timeline during a dub.
    """
    try:
        if sys.platform == "win32":
            BELOW_NORMAL_PRIORITY_CLASS = 0x00004000
            ctypes.windll.kernel32.SetPriorityClass(ctypes.windll.kernel32.GetCurrentProcess(), BELOW_NORMAL_PRIORITY_CLASS)
        else:
            os.nice(5)
    except Exception as error:  # noqa: BLE001 — best effort
        logger.warning("Could not lower process priority: %s", error)


def _configure_threads() -> int:
    """Torch's intra-op pool follows OMP_NUM_THREADS, which the supervisor sets to one per physical core."""
    threads = _positive_int("OMP_NUM_THREADS", torch.get_num_threads(), 256)
    torch.set_num_threads(threads)
    return threads


def _cpu_has_bf16() -> bool:
    probe = getattr(torch.cpu, "_is_avx512_bf16_supported", None)
    if callable(probe):
        try:
            return bool(probe())
        except Exception:  # noqa: BLE001
            pass
    return "AMX" in str(torch.backends.cpu.get_cpu_capability())


def _cuda_compute_capability(device: str) -> Optional[float]:
    """``major.minor`` of a CUDA device as a number (7.5 for a GTX 1660 SUPER), or nothing off-card."""
    if not str(device).startswith("cuda") or not torch.cuda.is_available():
        return None
    try:
        major, minor = torch.cuda.get_device_capability(torch.device(device))
        return major + minor / 10
    except Exception:  # noqa: BLE001
        return None


_ACOUSTIC_DTYPES = {"bf16": torch.bfloat16, "fp16": torch.float16, "fp32": torch.float32}


def _acoustic_dtype_for(device: str, checkpoint_dtype: torch.dtype, requested: str = "auto") -> torch.dtype:
    """What the acoustic stack (feature encoder, diffusion decoder) runs in on a GPU.

    The checkpoint is bfloat16, and on Ampere (compute capability 8.x) and newer that is also the
    fast path.  Turing and Volta (7.x: GTX 16-series, RTX 20-series, T4) have no bfloat16 tensor
    cores; PyTorch still runs bfloat16 there, through a path several times slower than the same
    card's float16 rate — on a customer's GTX 1660 SUPER, slow enough that the card read as idle.
    Float16 has the same mantissa headroom as bfloat16 has exponent headroom, and the diffusion
    decoder's activations are normalised (its RMSNorm accumulates in float32) and its inputs are
    unit-scale latents, so it stays well inside float16's range.  The AudioVAE is float32 whatever
    this says.  ``VOXCPM_ACOUSTIC_DTYPE=bf16|fp16|fp32`` overrides the rule for support and for the
    benchmark's columns.
    """
    requested = (requested or "auto").strip().lower()
    if requested in _ACOUSTIC_DTYPES:
        return _ACOUSTIC_DTYPES[requested]
    capability = _cuda_compute_capability(device)
    if capability is not None and capability < 8.0 and checkpoint_dtype == torch.bfloat16:
        return torch.float16
    return checkpoint_dtype


# --------------------------------------------------------------------------------------------- #
# Upstream patches, each pinned to the source it was written against
# --------------------------------------------------------------------------------------------- #


def _source_hash(function) -> str:
    return hashlib.sha256(inspect.getsource(function).encode("utf-8")).hexdigest()


# voxcpm @ ee8161e9e1b7b082cb5721a3a9980da4204401e6
UPSTREAM_ATTENTION_STEP_HASH = "2b730666fa3260009f145bb3c057dc09a2666073052574e0121ddfac5de6fc17"
UPSTREAM_INFERENCE_HASH = "71aed851a47c72fc671a8882a2fc24ccf0b70ecb525f9ff2e9d0bac4a95452af"
UPSTREAM_ENCODE_WAV_HASH = "2642bc4b2a407785ce52fbb1070d8e924adf4292150b210b1f2e59fbe6376401"
# The streaming loader replicates `from_local`'s setup steps and relies on `__init__` building the
# KV caches with an explicit device and taking the VAE as an argument; both are pinned.
UPSTREAM_FROM_LOCAL_HASH = "b2cdcae6667c02b23ab004458bcf201be65137c37c975512e34b0a27f8b4ec7f"
UPSTREAM_INIT_HASH = "02ab6f908c1ba9b3603bd88dbb51a43e64412c8ffefc94090a15add7f478241c"
UPSTREAM_ROPE_INIT_HASH = "7ff3d2049f726330f94af4222928f8a9d9a156834d4ea45db6f78202cd820159"


def _install_sliced_attention() -> bool:
    """Attend over the tokens that exist, not over the whole static cache.

    Upstream's ``forward_step`` builds a mask over all ``max_length`` slots and hands SDPA the full
    cache.  For a 200-token utterance that is 40x more key/value traffic than needed, per layer, per
    step.  Slicing to ``position_id + 1`` is numerically identical (the masked slots contributed
    nothing) and removes the mask altogether.
    """
    from voxcpm.modules.minicpm4 import model as minicpm

    attention = minicpm.MiniCPMAttention
    if _source_hash(attention.forward_step) != UPSTREAM_ATTENTION_STEP_HASH:
        logger.warning("Upstream attention changed; keeping its own forward_step.")
        return False
    apply_rotary_pos_emb = minicpm.apply_rotary_pos_emb

    def forward_step(self, hidden_states, position_emb, position_id, kv_cache):
        bsz, _ = hidden_states.size()
        query_states = self.q_proj(hidden_states).view(bsz, 1, self.num_heads, self.head_dim).transpose(1, 2)
        key_states = self.k_proj(hidden_states).view(bsz, 1, self.num_key_value_heads, self.head_dim).transpose(1, 2)
        value_states = self.v_proj(hidden_states).view(bsz, 1, self.num_key_value_heads, self.head_dim).transpose(1, 2)
        if position_emb is not None:
            cos, sin = position_emb
            query_states, key_states = apply_rotary_pos_emb(query_states, key_states, cos, sin)
        key_cache, value_cache = kv_cache
        key_cache[:, :, position_id, :] = key_states
        value_cache[:, :, position_id, :] = value_states
        end = int(position_id) + 1
        attn_output = torch.nn.functional.scaled_dot_product_attention(
            query_states.contiguous(),
            key_cache[:, :, :end, :].contiguous(),
            value_cache[:, :, :end, :].contiguous(),
            enable_gqa=True,
        )
        attn_output = attn_output.transpose(1, 2).contiguous().reshape(bsz, self.num_heads * self.head_dim)
        return self.o_proj(attn_output)

    attention.forward_step = forward_step
    return True


def _install_clear_cache_overflow() -> None:
    """Turn a prompt longer than the cache into a sentence instead of a shape error mid-load."""
    from voxcpm.modules.minicpm4.cache import StaticKVCache

    original = StaticKVCache.fill_caches

    def fill_caches(self, kv_caches):
        length = kv_caches[0][0].size(2)
        if length > self.max_length:
            raise ValueError(
                f"The reference clip and text need {length} tokens of context but the server was started with "
                f"a {self.max_length}-token cache. Use a shorter reference clip or raise VOXCPM_KV_MAX_LENGTH."
            )
        return original(self, kv_caches)

    StaticKVCache.fill_caches = fill_caches


def _resize_kv_caches(model, max_length: int, device, dtype: torch.dtype) -> None:
    """Re-allocate both static caches.  ``kv_cache`` is a plain attribute, so ``model.to`` never moves it."""
    for lm in (model.base_lm, model.residual_lm):
        # Dropped before the replacement is made, so the two never sit in memory together.
        lm.kv_cache = None
        lm.setup_cache(1, max_length, device, dtype)


# --------------------------------------------------------------------------------------------- #
# Hybrid placement
# --------------------------------------------------------------------------------------------- #

from voxcpm.model.voxcpm2 import VoxCPM2Model  # noqa: E402
from voxcpm.model.utils import get_dtype  # noqa: E402

try:
    from tqdm import tqdm
except ImportError:  # pragma: no cover
    def tqdm(iterable, **_kwargs):
        return iterable

try:
    from einops import rearrange
except ImportError:  # pragma: no cover
    rearrange = None


_SAFETENSORS_DTYPES = {
    "BF16": torch.bfloat16, "F16": torch.float16, "F32": torch.float32, "F64": torch.float64,
    "I8": torch.int8, "I16": torch.int16, "I32": torch.int32, "I64": torch.int64, "U8": torch.uint8, "BOOL": torch.bool,
}


def _read_exact(handle, buffer: memoryview) -> None:
    """``readinto`` until the view is full; an unbuffered handle may answer short."""
    filled = 0
    while filled < len(buffer):
        count = handle.readinto(buffer[filled:])
        if not count:
            raise EOFError("safetensors data ended early")
        filled += count


def _read_safetensors_into(path: str, target_for_key, skipped: list) -> dict:
    """Read a safetensors file one tensor at a time, each straight into its final device and dtype.

    Upstream's ``load_file`` maps the whole 4.3 GB file and ``load_state_dict`` then touches every
    page, so the mapped file sits in the working set beside the model until the map is dropped.
    Plain sequential reads from an unbuffered handle go through the page cache instead, and the
    only host memory this holds at once is the tensors that stay on the host plus one staging
    buffer the size of the largest tensor (287 MB here).  The format is eight bytes of little-endian
    header length, a JSON header, then the data block the header's offsets index into.
    """
    import struct

    with open(path, "rb", buffering=0) as handle:
        header_length = struct.unpack("<Q", handle.read(8))[0]
        header = json.loads(handle.read(header_length))
        data_start = 8 + header_length
        entries = sorted(((key, entry) for key, entry in header.items() if key != "__metadata__"),
                         key=lambda item: item[1]["data_offsets"][0])
        largest = max((entry["data_offsets"][1] - entry["data_offsets"][0] for _, entry in entries), default=0)
        staging: Optional[torch.Tensor] = None
        loaded: dict = {}
        for key, entry in entries:
            target = target_for_key(key)
            if target is None:
                skipped.append(key)
                continue
            device, dtype = target
            file_dtype = _SAFETENSORS_DTYPES[entry["dtype"]]
            # Only floating-point weights follow the placement's dtype, as ``module.to(dtype)`` does.
            if not file_dtype.is_floating_point:
                dtype = file_dtype
            shape = tuple(entry["shape"])
            begin, end = entry["data_offsets"]
            nbytes = end - begin
            handle.seek(data_start + begin)
            if str(device) == "cpu" and dtype == file_dtype:
                tensor = torch.empty(shape, dtype=dtype)
                if nbytes:
                    _read_exact(handle, memoryview(tensor.view(-1).view(torch.uint8).numpy()))
            else:
                if staging is None:
                    staging = torch.empty(largest, dtype=torch.uint8)
                if nbytes:
                    _read_exact(handle, memoryview(staging[:nbytes].numpy()))
                source = staging[:nbytes].view(file_dtype).view(shape)
                tensor = torch.empty(shape, dtype=dtype, device=device)
                tensor.copy_(source)
            loaded[key] = tensor
        return loaded


def _load_vae_state_dict(path: str) -> dict:
    """The AudioVAE weights, found the way upstream's ``from_local`` finds them."""
    safetensors_path = os.path.join(path, "audiovae.safetensors")
    pth_path = os.path.join(path, "audiovae.pth")
    if os.path.exists(safetensors_path):
        from safetensors.torch import load_file
        return load_file(safetensors_path, device="cpu")
    if os.path.exists(pth_path):
        checkpoint = torch.load(pth_path, map_location="cpu", weights_only=True)
        return checkpoint.get("state_dict", checkpoint)
    raise FileNotFoundError(f"AudioVAE checkpoint not found. Expected either {safetensors_path} or {pth_path}")


# Which loader built the model this process serves; reported in the diagnostics line.
_LOADER_STATE = {"loader": "upstream"}


class VoxCPM2Hybrid(VoxCPM2Model):
    """The language models on one device and dtype, the acoustic stack on another.

    Constructed with ``device="cpu"`` so every base-class ``.to(self.device)`` — all of which target
    language-model inputs — stays correct and the static caches land beside the language models.
    Only the three methods that cross the seam are replaced.  The acoustic device may itself be the
    CPU: that is how a float32 language model is combined with the checkpoint's bfloat16 acoustic
    stack without a GPU.
    """

    LM_MODULES = ("base_lm", "residual_lm", "fsq_layer", "fusion_concat_proj", "stop_proj", "stop_head",
                  "lm_to_dit_proj", "res_to_dit_proj")
    ACOUSTIC_MODULES = ("feat_encoder", "feat_decoder", "enc_to_lm_proj")

    lm_device: str = "cpu"
    acoustic_device: str = "cpu"
    lm_dtype: torch.dtype = torch.bfloat16
    acoustic_dtype: torch.dtype = torch.bfloat16
    kv_max_length: int = 8192

    @staticmethod
    def _acoustic_dtype(placement: dict, acoustic_device: str, lm_dtype: torch.dtype, checkpoint_dtype: torch.dtype) -> torch.dtype:
        """On the CPU the acoustic stack follows the language models, because the reason for float32
        there (no bfloat16 hardware) applies to every matmul, and the diffusion decoder runs the most
        of them per second of audio.  On a GPU it keeps the checkpoint's bfloat16 where the card has
        it and takes float16 where only that is fast — see ``_acoustic_dtype_for``."""
        if acoustic_device == "cpu":
            return lm_dtype
        return _acoustic_dtype_for(acoustic_device, checkpoint_dtype, placement.get("acoustic_dtype", "auto"))

    @classmethod
    def _from_local_streaming(cls, path: str, placement: dict):
        """Build the model without the loader's transient copies.

        Upstream's ``from_local`` random-initialises 2.4 B parameters in float32 (8.9 GB), casts them
        to bfloat16, then maps the whole 4.3 GB checkpoint beside them: an 11 GB peak on the host
        for a model whose resident half is 3.5 GB.  On a 16 GB laptop with a browser open that peak
        is the difference between starting and not.  Here the skeleton is built on the ``meta``
        device (no memory), each tensor is read from disk straight into its final device and
        dtype, and the only tensors the checkpoint does not carry — the rotary tables, computed
        from the config alone — are rebuilt afterwards.  Anything unexpected raises, and the caller
        falls back to upstream's loader.
        """
        import itertools

        from transformers import LlamaTokenizerFast
        from voxcpm.model.voxcpm2 import VoxCPMConfig
        from voxcpm.modules.audiovae import AudioVAEV2
        from voxcpm.modules.minicpm4.model import MiniCPMLongRoPE

        # The same setup steps as upstream (config, tokenizer, VAE), outside the meta context: the
        # tokenizer holds no tensors and the VAE is small enough (0.35 GB) to load the ordinary way.
        with open(os.path.join(path, "config.json"), "r", encoding="utf-8") as handle:
            config = VoxCPMConfig.model_validate_json(handle.read())
        tokenizer = LlamaTokenizerFast.from_pretrained(path)
        audio_vae_config = getattr(config, "audio_vae_config", None)
        audio_vae = AudioVAEV2(config=audio_vae_config) if audio_vae_config else AudioVAEV2()
        vae_state = _load_vae_state_dict(path)
        vae_result = audio_vae.load_state_dict(vae_state, strict=False)
        del vae_state
        if vae_result.missing_keys or vae_result.unexpected_keys:
            raise RuntimeError(f"AudioVAE checkpoint mismatch: {vae_result.missing_keys[:3]} missing, "
                               f"{vae_result.unexpected_keys[:3]} unexpected")
        audio_vae = audio_vae.to(torch.float32)

        with torch.device("meta"):
            model = cls(config, tokenizer, audio_vae, None, device="cpu")

        lm_dtype = placement["lm_dtype"]
        acoustic_device = placement["acoustic_device"]
        acoustic_dtype = cls._acoustic_dtype(placement, acoustic_device, lm_dtype, get_dtype(model.config.dtype))
        lm_modules, acoustic_modules = set(cls.LM_MODULES), set(cls.ACOUSTIC_MODULES)

        def target_for_key(key: str):
            top = key.split(".", 1)[0]
            if top in lm_modules:
                return "cpu", lm_dtype
            if top in acoustic_modules:
                return acoustic_device, acoustic_dtype
            return None

        skipped: list = []
        state = _read_safetensors_into(os.path.join(path, "model.safetensors"), target_for_key, skipped)
        if skipped:
            logger.info("Streaming loader skipped %d checkpoint tensors outside the known modules (e.g. %s)",
                        len(skipped), skipped[0])
        result = model.load_state_dict(state, strict=False, assign=True)
        del state
        missing = [key for key in result.missing_keys if not key.startswith("audio_vae.")]
        if missing or result.unexpected_keys:
            raise RuntimeError(f"checkpoint mismatch: {missing[:3]} missing, {list(result.unexpected_keys)[:3]} unexpected")

        # The rotary tables are non-persistent buffers computed in the module's __init__ from its
        # config, so a fresh instance is the exact tensor upstream would have had.
        for parent in list(model.modules()):
            for name, child in list(parent.named_children()):
                if isinstance(child, MiniCPMLongRoPE) and any(buffer.is_meta for buffer in child.buffers()):
                    setattr(parent, name, MiniCPMLongRoPE(child.config))

        leftovers = [name for name, tensor in itertools.chain(model.named_parameters(), model.named_buffers())
                     if tensor.is_meta]
        if leftovers:
            raise RuntimeError(f"{len(leftovers)} tensors were never materialised (e.g. {leftovers[0]})")
        return model

    @classmethod
    def from_local(cls, path, optimize=True, training=False, device=None, lora_config=None):  # noqa: ARG003
        placement = _HYBRID_PLACEMENT
        model = None
        # The escape hatch exists for support and for the benchmark's baseline column.
        streaming_wanted = os.environ.get("VOXCPM_DISABLE_STREAMING_LOADER") != "1"
        if lora_config is None and streaming_wanted and _loader_sources_match():
            try:
                model = cls._from_local_streaming(path, placement)
                _LOADER_STATE["loader"] = "streaming"
            except Exception as error:  # noqa: BLE001
                logger.warning("Streaming loader failed (%s); using upstream's loader.", error)
                model = None
                import gc
                gc.collect()
                if torch.cuda.is_available():
                    torch.cuda.empty_cache()
        if model is None:
            _LOADER_STATE["loader"] = "upstream"
            model = super().from_local(path, optimize=False, training=False, device="cpu", lora_config=lora_config)
        model.lm_device = "cpu"
        model.acoustic_device = placement["acoustic_device"]
        model.lm_dtype = placement["lm_dtype"]
        # Bfloat16 on an Ampere-or-newer card, float16 on a Turing one, the language models' dtype
        # on the CPU — see ``_acoustic_dtype``.
        model.acoustic_dtype = cls._acoustic_dtype(placement, model.acoustic_device, model.lm_dtype, get_dtype(model.config.dtype))
        model.kv_max_length = placement["kv_max_length"]
        # No-ops for tensors the streaming loader already placed; this is where its rebuilt rotary
        # tables get their device and dtype.
        for name in cls.LM_MODULES:
            getattr(model, name).to(device=model.lm_device, dtype=model.lm_dtype)
        for name in cls.ACOUSTIC_MODULES:
            getattr(model, name).to(device=model.acoustic_device, dtype=model.acoustic_dtype)
        model.audio_vae.to(device=model.acoustic_device, dtype=torch.float32)
        _resize_kv_caches(model, model.kv_max_length, model.lm_device, model.lm_dtype)
        return model.eval()

    def _encode_wav(self, wav_path: str, padding_mode: str = "right", trim_silence_vad: bool = False) -> torch.Tensor:
        import librosa
        from voxcpm.model.voxcpm2 import _trim_audio_silence_vad

        audio, _ = librosa.load(wav_path, sr=self._encode_sample_rate, mono=True)
        audio = torch.from_numpy(audio).unsqueeze(0)
        if trim_silence_vad:
            audio = _trim_audio_silence_vad(audio, self._encode_sample_rate, max_silence_ms=200.0)
        patch_len = self.patch_size * self.chunk_size
        if audio.size(1) % patch_len != 0:
            padding_size = patch_len - audio.size(1) % patch_len
            pad = (padding_size, 0) if padding_mode == "left" else (0, padding_size)
            audio = torch.nn.functional.pad(audio, pad)
        feat = self.audio_vae.encode(audio.to(self.acoustic_device), self._encode_sample_rate).cpu()
        return feat.view(self.audio_vae.latent_dim, -1, self.patch_size).permute(1, 2, 0)

    @torch.inference_mode()
    def _inference(self, text, text_mask, feat, feat_mask, min_len=2, max_len=2000, inference_timesteps=10,
                   cfg_value=2.0, streaming=False, streaming_prefix_len=4):
        B, T, P, D = feat.shape
        lm, ac = (self.lm_device, self.lm_dtype), (self.acoustic_device, self.acoustic_dtype)
        # A prompt that cannot fit beside the longest allowed answer fails here, in words.
        max_len = max(1, min(max_len, self.kv_max_length - T - text.size(1) - 2))

        feat = feat.to(*ac)
        text, text_mask, feat_mask = text.to(lm[0]), text_mask.to(lm[0]), feat_mask.to(lm[0])

        feat_embed = self.enc_to_lm_proj(self.feat_encoder(feat)).to(*lm)  # [b, t, h_lm]
        scale_emb = self.config.lm_config.scale_emb if self.config.lm_config.use_mup else 1.0
        text_embed = self.base_lm.embed_tokens(text) * scale_emb
        combined_embed = text_mask.unsqueeze(-1) * text_embed + feat_mask.unsqueeze(-1) * feat_embed

        prefix_feat_cond = feat[:, -1, ...]  # b, p, d — acoustic device
        pred_feat_seq = []
        curr_embed = None

        has_continuation_audio = feat_mask[0, -1].item() == 1
        context_len = 0
        if has_continuation_audio:
            audio_indices = feat_mask.squeeze(0).nonzero(as_tuple=True)[0]
            context_len = min(streaming_prefix_len - 1, len(audio_indices))
            last_audio_indices = audio_indices[-context_len:].to(feat.device)
            pred_feat_seq = list(feat[:, last_audio_indices, :, :].split(1, dim=1))

        enc_outputs, kv_cache_tuple = self.base_lm(inputs_embeds=combined_embed, is_causal=True)
        self.base_lm.kv_cache.fill_caches(kv_cache_tuple)
        enc_outputs = self.fsq_layer(enc_outputs) * feat_mask.unsqueeze(-1) + enc_outputs * text_mask.unsqueeze(-1)
        lm_hidden = enc_outputs[:, -1, :]

        residual_enc_inputs = self.fusion_concat_proj(torch.cat((enc_outputs, feat_mask.unsqueeze(-1) * feat_embed), dim=-1))
        residual_enc_outputs, residual_kv_cache_tuple = self.residual_lm(inputs_embeds=residual_enc_inputs, is_causal=True)
        self.residual_lm.kv_cache.fill_caches(residual_kv_cache_tuple)
        residual_hidden = residual_enc_outputs[:, -1, :]

        for i in tqdm(range(max_len), disable=True):
            dit_hidden = torch.cat((self.lm_to_dit_proj(lm_hidden), self.res_to_dit_proj(residual_hidden)), dim=-1)
            pred_feat = self.feat_decoder(
                mu=dit_hidden.to(*ac),
                patch_size=self.patch_size,
                cond=prefix_feat_cond.transpose(1, 2).contiguous(),
                n_timesteps=inference_timesteps,
                cfg_value=cfg_value,
            ).transpose(1, 2)  # [b, p, d]

            curr_embed = self.enc_to_lm_proj(self.feat_encoder(pred_feat.unsqueeze(1))).to(*lm)  # b, 1, c
            pred_feat_seq.append(pred_feat.unsqueeze(1))
            prefix_feat_cond = pred_feat

            if streaming:
                feat_pred = rearrange(pred_feat.unsqueeze(1), "b t p d -> b d (t p)", b=B, p=self.patch_size)
                yield feat_pred, pred_feat_seq, context_len
                if len(pred_feat_seq) > streaming_prefix_len:
                    pred_feat_seq = pred_feat_seq[-streaming_prefix_len:]

            stop_flag = self.stop_head(self.stop_actn(self.stop_proj(lm_hidden))).argmax(dim=-1)[0].cpu().item()
            if i > min_len and stop_flag == 1:
                break

            lm_hidden = self.base_lm.forward_step(
                curr_embed[:, 0, :], torch.tensor([self.base_lm.kv_cache.step()], device=curr_embed.device)
            ).clone()
            lm_hidden = self.fsq_layer(lm_hidden)
            curr_residual_input = self.fusion_concat_proj(torch.cat((lm_hidden, curr_embed[:, 0, :]), dim=-1))
            residual_hidden = self.residual_lm.forward_step(
                curr_residual_input, torch.tensor([self.residual_lm.kv_cache.step()], device=curr_embed.device)
            ).clone()

        if not streaming:
            pred_feat_seq = torch.cat(pred_feat_seq, dim=1)
            feat_pred = rearrange(pred_feat_seq, "b t p d -> b d (t p)", b=B, p=self.patch_size)
            generated_feat = pred_feat_seq[:, context_len:, :, :].squeeze(0).cpu()
            yield feat_pred, generated_feat, context_len


_HYBRID_PLACEMENT = {"acoustic_device": "cpu", "lm_dtype": torch.bfloat16, "kv_max_length": 8192, "acoustic_dtype": "auto"}


def _hybrid_sources_match() -> bool:
    return (_source_hash(VoxCPM2Model._inference) == UPSTREAM_INFERENCE_HASH
            and _source_hash(VoxCPM2Model._encode_wav) == UPSTREAM_ENCODE_WAV_HASH)


def _loader_sources_match() -> bool:
    """Whether upstream still loads the way the streaming loader assumes; otherwise it stays off."""
    from voxcpm.modules.minicpm4.model import MiniCPMLongRoPE

    matches = (_source_hash(VoxCPM2Model.from_local) == UPSTREAM_FROM_LOCAL_HASH
               and _source_hash(VoxCPM2Model.__init__) == UPSTREAM_INIT_HASH
               and _source_hash(MiniCPMLongRoPE.__init__) == UPSTREAM_ROPE_INIT_HASH)
    if not matches:
        logger.warning("Upstream VoxCPM2 loader changed; using its own loader (higher memory peak).")
    return matches


def _guard_vae_decode_oom(tts_model) -> None:
    """A long clip's VAE decode is the one allocation that scales with output length.

    On a 4 GB card the hybrid split leaves a few hundred megabytes of margin; a paragraph-long line
    can exceed it in the final decode alone.  Rather than fail the line, decode it on the CPU — a
    few seconds of float32 convolution — and put the VAE back.
    """
    if not tts_model.acoustic_device.startswith("cuda"):
        return
    vae = tts_model.audio_vae
    original = vae.decode

    def decode(latent, *args, **kwargs):
        try:
            return original(latent, *args, **kwargs)
        except torch.cuda.OutOfMemoryError:
            logger.warning("VAE decode ran out of GPU memory; decoding this clip on the CPU.")
            torch.cuda.empty_cache()
            vae.to("cpu")
            try:
                return original(latent.cpu(), *args, **kwargs)
            finally:
                vae.to(tts_model.acoustic_device)

    vae.decode = decode


# --------------------------------------------------------------------------------------------- #
# Server
# --------------------------------------------------------------------------------------------- #


class PromptFeatureCache:
    """Bounded LRU of encoded voice references.

    Keyed on the file's identity (path, size, mtime) and the transcript rather than a digest of the
    bytes: the desktop side uploads a reference once per server and reuses the path, so re-hashing a
    ten-second WAV for every one of two hundred lines bought nothing.  VoxCPM's prompt cache is kept on
    CPU by upstream code and transferred with the small request tensors; the expensive librosa decode,
    resample, and AudioVAE encode happen only once per voice.
    """

    def __init__(self, maximum: int) -> None:
        self.maximum = maximum
        self._items: OrderedDict[tuple, dict] = OrderedDict()
        self._lock = Lock()

    @staticmethod
    def _key(path: str, prompt_text: str) -> tuple:
        info = os.stat(path)
        return (os.path.normcase(os.path.abspath(path)), info.st_size, info.st_mtime_ns, prompt_text)

    def get_or_build(self, tts_model, path: str, prompt_text: str) -> tuple[dict, bool]:
        key = self._key(path, prompt_text)
        with self._lock:
            known = self._items.pop(key, None)
            if known is not None:
                self._items[key] = known
                return known, True

            kwargs = {"reference_wav_path": path}
            if prompt_text:
                kwargs.update(prompt_wav_path=path, prompt_text=prompt_text)
            built = tts_model.build_prompt_cache(**kwargs)
            self._items[key] = built
            while len(self._items) > self.maximum:
                self._items.popitem(last=False)
            return built, False

    def size(self) -> int:
        with self._lock:
            return len(self._items)


class VoxCPMRuntime:
    def __init__(self, model_id: str, requested_device: str, cpu_dtype: str, kv_max_length: int,
                 acoustic_dtype: str = "auto") -> None:
        self.requested_device = requested_device
        self.triton_available = importlib.util.find_spec("triton") is not None
        self.threads = _configure_threads()
        self.prompt_cache = PromptFeatureCache(_positive_int("VOXCPM_PROMPT_CACHE_SIZE", 32, 256))
        self.cpu_bf16 = _cpu_has_bf16()
        # The escape hatch exists for the benchmark, which needs upstream's own attention as a baseline.
        self.sliced_attention = (os.environ.get("VOXCPM_DISABLE_SLICED_ATTENTION") != "1") and _install_sliced_attention()
        _install_clear_cache_overflow()

        # What the language models run in when they run on the CPU.  Measured on an i5-11400H
        # (no AVX512-BF16): float32 is 1.5x faster when the diffusion decoder also runs on the CPU,
        # because that is where most of the emulated matmuls are; with the decoder on a GPU the
        # language models' decode steps are memory-bound and bfloat16's half-size weights win.
        if cpu_dtype == "auto":
            cpu_dtype = "bf16" if (self.cpu_bf16 or requested_device == "hybrid") else "fp32"
        self.lm_dtype_name = cpu_dtype
        lm_dtype = torch.float32 if cpu_dtype == "fp32" else torch.bfloat16
        self.kv_max_length = kv_max_length

        if requested_device == "hybrid":
            if not torch.cuda.is_available():
                raise RuntimeError("Hybrid mode needs a CUDA-capable PyTorch and an NVIDIA GPU.")
            self.device = "hybrid"
            self.hybrid = True
            acoustic_device = "cuda"
        else:
            self.device = resolve_runtime_device(requested_device, "cuda")
            # A float32 language model or a smaller cache on the CPU goes through the same subclass,
            # with the acoustic stack beside it.  Plain CUDA and plain bf16 CPU use upstream untouched.
            self.hybrid = self.device == "cpu" and (lm_dtype != torch.bfloat16 or kv_max_length != 8192)
            acoustic_device = "cpu"
        if self.hybrid and not _hybrid_sources_match():
            logger.warning("Upstream VoxCPM2 changed under the hybrid adapter; falling back to plain %s.",
                           "cuda" if requested_device == "hybrid" else self.device)
            self.hybrid = False
            self.device = "cuda" if requested_device == "hybrid" else self.device
        # torch.compile's CUDA backend needs Triton.  Upstream catches this failure and silently
        # continues, which looks like an optimized server while paying eager-mode dispatch costs.
        # The hybrid split is never compiled: CUDA graphs would pool memory the card does not have.
        self.compile_enabled = (not self.hybrid) and self.device.startswith("cuda") and self.triton_available

        if self.hybrid:
            _HYBRID_PLACEMENT.update(acoustic_device=acoustic_device, lm_dtype=lm_dtype, kv_max_length=kv_max_length,
                                     acoustic_dtype=acoustic_dtype)
            voxcpm.core.VoxCPM2Model = VoxCPM2Hybrid
            load_device = "cpu"
            logger.info("Loading VoxCPM2 from %s: language models on cpu (%s, %d-token cache), acoustic stack on %s (%s)",
                        model_id, cpu_dtype, kv_max_length, acoustic_device,
                        acoustic_dtype if acoustic_device == "cpu" or acoustic_dtype != "auto"
                        else str(_acoustic_dtype_for(acoustic_device, torch.bfloat16)).replace("torch.", ""))
        else:
            load_device = self.device
            logger.info("Loading VoxCPM2 from %s on %s", model_id, self.device)
        torch.backends.cudnn.benchmark = False
        self.pipeline = voxcpm.VoxCPM.from_pretrained(
            model_id,
            device=load_device,
            optimize=self.compile_enabled,
            load_denoiser=False,
            local_files_only=Path(model_id).is_dir(),
        )
        self.tts_model = self.pipeline.tts_model
        if self.hybrid:
            _guard_vae_decode_oom(self.tts_model)
        self._emit_diagnostics()

    def diagnostics(self) -> dict:
        devices = sorted({str(parameter.device) for parameter in self.tts_model.parameters()})
        dtypes = sorted({str(parameter.dtype).replace("torch.", "") for parameter in self.tts_model.parameters()})
        gpu = None
        if torch.cuda.is_available():
            index = torch.cuda.current_device()
            properties = torch.cuda.get_device_properties(index)
            free, total = torch.cuda.mem_get_info(index)
            gpu = {"name": properties.name, "vramBytes": properties.total_memory, "vramFreeBytes": free,
                   "vramReservedBytes": torch.cuda.memory_reserved(index),
                   "computeCapability": properties.major + properties.minor / 10}
        acoustic = getattr(self.tts_model, "acoustic_dtype", None) if self.hybrid else None
        acoustic_name = str(acoustic).replace("torch.", "") if acoustic is not None else ("bf16" if self.device.startswith("cuda") else None)
        return {
            "requestedDevice": self.requested_device,
            "resolvedDevice": self.device,
            "torchVersion": torch.__version__,
            "cudaRuntime": torch.version.cuda,
            "cudaAvailable": torch.cuda.is_available(),
            "bf16Supported": bool(torch.cuda.is_available() and torch.cuda.is_bf16_supported()),
            "tritonAvailable": self.triton_available,
            "compileEnabled": self.compile_enabled,
            "modelDevices": devices,
            "modelDtypes": dtypes,
            "gpu": gpu,
            "promptCacheEntries": self.prompt_cache.size(),
            "threads": self.threads,
            "cpuBf16": self.cpu_bf16,
            "lmDtype": self.lm_dtype_name if self.hybrid or self.device == "cpu" else "bf16",
            "acousticDtype": {"bfloat16": "bf16", "float16": "fp16", "float32": "fp32"}.get(acoustic_name, acoustic_name),
            "kvMaxLength": self.kv_max_length if self.hybrid else 8192,
            "slicedAttention": self.sliced_attention,
            "hybrid": self.hybrid,
            "loader": _LOADER_STATE["loader"],
        }

    def _emit_diagnostics(self) -> None:
        # Machine-readable and deliberately one line: the Electron supervisor recognizes this
        # prefix and adds the object to the server snapshot shown in Settings/support logs.
        logger.info("VOXCPM_RUNTIME=%s", json.dumps(self.diagnostics(), separators=(",", ":")))

    def _release_memory(self) -> None:
        """Return the allocator's slack to the card, but only when there is enough of it to matter."""
        if not torch.cuda.is_available():
            return
        slack = torch.cuda.memory_reserved() - torch.cuda.memory_allocated()
        if slack > 512 * 1024 * 1024:
            torch.cuda.empty_cache()

    def generate(
        self,
        text: str,
        control_instruction: str = "",
        reference_wav_path: Optional[str] = None,
        use_prompt_text: bool = False,
        prompt_text: str = "",
        cfg: float = 2.0,
        normalize: bool = False,
        _denoise: bool = False,
        dit_steps: int = 10,
        seed: Optional[int] = None,
    ):
        target = (text or "").strip()
        if not target:
            raise ValueError("Target text must not be empty.")
        prompt = (prompt_text or "").strip() if use_prompt_text and reference_wav_path else ""
        control = "" if prompt else re.sub(r"[()（）]", "", control_instruction or "").strip()
        final_text = f"({control}){target}" if control else target

        if normalize:
            if self.pipeline.text_normalizer is None:
                from voxcpm.utils.text_normalize import TextNormalizer

                self.pipeline.text_normalizer = TextNormalizer()
            final_text = self.pipeline.text_normalizer.normalize(final_text)

        try:
            with torch.inference_mode():
                if reference_wav_path:
                    cached, hit = self.prompt_cache.get_or_build(self.tts_model, reference_wav_path, prompt)
                    logger.info("Reference feature cache %s (%d entries)", "hit" if hit else "miss", self.prompt_cache.size())
                    wav, _, _ = self.tts_model.generate_with_prompt_cache(
                        target_text=final_text,
                        prompt_cache=cached,
                        inference_timesteps=int(dit_steps),
                        cfg_value=float(cfg),
                        retry_badcase=True,
                        seed=None if seed is None else int(seed),
                    )
                    waveform = wav.squeeze(0).cpu().numpy()
                    del wav
                else:
                    waveform = self.pipeline.generate(
                        text=final_text,
                        cfg_value=float(cfg),
                        inference_timesteps=int(dit_steps),
                        normalize=False,
                        denoise=False,
                        seed=None if seed is None else int(seed),
                    )
        finally:
            self._release_memory()

        successful_seed = getattr(self.tts_model, "last_successful_seed", seed)
        return (self.tts_model.sample_rate, np.asarray(waveform, dtype=np.float32)), successful_seed


# Local fonts only: the page must look the same on a machine with no internet, and Khmer target
# text needs a face that has the glyphs.
_UI_FONTS = ["Segoe UI", "Noto Sans Khmer", "Khmer OS Battambang", "Leelawadee UI", "system-ui", "sans-serif"]

_UI_CSS = """
.gradio-container { max-width: 1180px !important; margin: 0 auto !important; }
#vox-header { padding: 18px 4px 6px; }
#vox-header h1 { margin: 0; font-size: 26px; letter-spacing: -0.01em; }
#vox-header p { margin: 4px 0 0; opacity: 0.72; }
#vox-runtime { display: flex; flex-wrap: wrap; gap: 6px; padding: 0 4px 10px; }
#vox-runtime .chip { font-size: 12px; padding: 3px 10px; border-radius: 999px;
  border: 1px solid var(--border-color-primary); background: var(--background-fill-secondary); }
#vox-runtime .chip b { color: var(--color-accent); font-weight: 600; }
#vox-mode { padding: 10px 12px; border-radius: 8px; border-left: 3px solid var(--color-accent);
  background: var(--background-fill-secondary); }
#vox-mode p { margin: 0; font-size: 13px; }
#vox-generate { min-height: 48px; font-size: 16px; font-weight: 600; }
footer { display: none !important; }
"""

def _ui_theme():
    # Amber is the desktop app's accent; it is kept for the one primary action, so labels stay quiet.
    quiet = dict(block_label_background_fill="transparent", block_label_background_fill_dark="transparent",
                 block_title_background_fill="transparent", block_title_background_fill_dark="transparent",
                 block_label_text_color="*neutral_600", block_label_text_color_dark="*neutral_300",
                 block_title_text_color="*neutral_600", block_title_text_color_dark="*neutral_300",
                 block_title_padding="0", block_label_border_width="0px")
    return gr.themes.Soft(primary_hue="amber", neutral_hue="zinc", font=_UI_FONTS,
                          font_mono=["Consolas", "monospace"]).set(**quiet)


_MODE_HINTS = {
    "design": "**Voice Design** — no reference clip. Describe the voice in *Control instruction* "
              "(for example: *a calm middle-aged woman, slow and warm*), or leave it empty for a random voice.",
    "ultimate": "**Ultimate cloning** — the voice is copied from the reference clip alone. "
                "*Control instruction* can still steer the delivery.",
    "controllable": "**Transcript-guided cloning** — the clip and its exact transcript are used together for the "
                    "closest match. *Control instruction* is ignored in this mode.",
}


def _runtime_chips(runtime: "VoxCPMRuntime") -> str:
    info = runtime.diagnostics()
    gpu = info.get("gpu") or {}
    chips = [("Device", "hybrid (CPU + GPU)" if info.get("hybrid") else info.get("resolvedDevice"))]
    if gpu.get("name"):
        chips.append(("GPU", f"{gpu['name']} · {gpu['vramBytes'] / 2**30:.0f} GB"))
    chips.append(("Precision", " / ".join(str(v) for v in (info.get("lmDtype"), info.get("acousticDtype")) if v)))
    chips.append(("Output", f"{runtime.tts_model.sample_rate // 1000} kHz"))
    body = "".join(f'<span class="chip">{label} <b>{value}</b></span>' for label, value in chips if value)
    return f'<div id="vox-runtime">{body}</div>'


def create_interface(runtime: VoxCPMRuntime):
    def mode_changed(reference_path, guided):
        has_clip = bool(reference_path)
        guided = bool(guided and has_clip)
        mode = "controllable" if guided else "ultimate" if has_clip else "design"
        return _MODE_HINTS[mode], gr.update(visible=guided), gr.update(interactive=not guided)

    with gr.Blocks(title="VoxCPM2 Studio") as interface:
        gr.HTML('<div id="vox-header"><h1>VoxCPM2 Studio</h1>'
                "<p>Local voice generator, managed by Dubber Bisach. Nothing leaves this computer.</p></div>")
        gr.HTML(_runtime_chips(runtime))

        with gr.Row(equal_height=False):
            with gr.Column(scale=5):
                reference = gr.Audio(type="filepath", sources=["upload", "microphone"],
                                     label="Reference voice (optional, 5–20 s of clean speech)")
                use_prompt = gr.Checkbox(label="Transcript-guided cloning",
                                         info="Tick this when you can type exactly what the reference clip says.")
                prompt = gr.Textbox(label="Reference transcript", lines=2, visible=False,
                                    placeholder="The exact words spoken in the reference clip")
                control = gr.Textbox(label="Control instruction (optional)", lines=2,
                                     placeholder="e.g. a young man, cheerful, speaking quickly")
                mode_hint = gr.Markdown(_MODE_HINTS["design"], elem_id="vox-mode")

            with gr.Column(scale=6):
                text = gr.Textbox(label="Text to speak", lines=6, max_lines=14,
                                  placeholder="Type or paste the line to generate…")
                with gr.Accordion("Advanced settings", open=False):
                    with gr.Row():
                        cfg = gr.Slider(1.0, 5.0, value=2.0, step=0.1, label="CFG (guidance)",
                                        info="Higher follows the reference more closely; too high sounds strained.")
                        steps = gr.Slider(4, 30, value=10, step=1, label="Diffusion steps",
                                          info="More steps: finer detail, slower.")
                    with gr.Row():
                        seed = gr.Number(value=42, precision=0, label="Seed",
                                         info="Same seed + same inputs gives a near-identical take.")
                        normalize = gr.Checkbox(value=False, label="Normalize text",
                                                info="Spell out numbers and symbols (English/Chinese).")
                # Part of the 10-argument /generate contract the desktop client sends, but this
                # server never denoises, so it is not offered as a control.
                denoise = gr.Checkbox(value=False, label="Denoise reference", visible=False)
                generate = gr.Button("Generate speech", variant="primary", elem_id="vox-generate")
                audio = gr.Audio(label="Generated audio", interactive=False, autoplay=True)
                actual_seed = gr.Number(label="Seed used", interactive=False)

        for trigger in (reference.change, use_prompt.change):
            trigger(mode_changed, inputs=[reference, use_prompt], outputs=[mode_hint, prompt, control],
                    api_visibility="private", show_progress="hidden", queue=False)

        generate.click(
            runtime.generate,
            inputs=[text, control, reference, use_prompt, prompt, cfg, normalize, denoise, steps, seed],
            outputs=[audio, actual_seed],
            api_name="generate",
        )

        # A callable health API makes the loaded model—not merely an import test—observable to
        # operators and future clients.  It is harmlessly absent from the desktop's ordinary flow.
        health_trigger = gr.Button("Runtime health", visible=False)
        health = gr.JSON(visible=False)
        health_trigger.click(runtime.diagnostics, outputs=health, api_name="runtime_health")
    return interface


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    parser.add_argument("--model-id", default="openbmb/VoxCPM2")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8808)
    parser.add_argument("--device", default="auto", help="auto, cpu, cuda, cuda:N, or hybrid")
    parser.add_argument("--cpu-dtype", default=os.environ.get("VOXCPM_LM_DTYPE", "auto"), choices=["auto", "bf16", "fp32"],
                        help="dtype of the language models when they run on the CPU")
    parser.add_argument("--acoustic-dtype", default=os.environ.get("VOXCPM_ACOUSTIC_DTYPE", "auto"),
                        choices=["auto", "bf16", "fp16", "fp32"],
                        help="dtype of the acoustic stack on a GPU in hybrid mode; auto is bf16 on Ampere+, fp16 on Turing")
    parser.add_argument("--kv-max-length", type=int, default=_positive_int("VOXCPM_KV_MAX_LENGTH", 8192, 8192))
    parser.add_argument("--parent-pid", type=int, default=0, help="exit when this process exits")
    return parser


def main() -> None:
    args = build_parser().parse_args()
    if args.parent_pid > 0:
        _install_parent_watchdog(args.parent_pid)
    _lower_process_priority()

    runtime = VoxCPMRuntime(args.model_id, args.device, args.cpu_dtype, max(512, min(8192, args.kv_max_length)),
                            acoustic_dtype=args.acoustic_dtype)
    create_interface(runtime).queue(max_size=10, default_concurrency_limit=1).launch(
        server_name=args.host,
        server_port=args.port,
        show_error=True,
        theme=_ui_theme(),
        css=_UI_CSS,
    )


if __name__ == "__main__":
    main()
