#!/usr/bin/env python3
# -*- encoding: utf-8 -*-
# Copyright FunASR (https://github.com/alibaba-damo-academy/FunASR). All Rights Reserved.
#  MIT License  (https://opensource.org/licenses/MIT)

import argparse
import logging
import os
import sys

import torch
from typeguard import check_argument_types

from funasr.build_utils.build_speech2output import build_speech2output
from funasr.torch_utils.set_all_random_seed import set_all_random_seed
from funasr.utils import config_argparse
from funasr.utils.cli_utils import get_commandline_args
from funasr.utils.types import str2bool
from funasr.utils.types import str2triple_str
from funasr.utils.types import str_or_none


def get_parser():
    parser = config_argparse.ArgumentParser(
        description="ASR Decoding",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )

    # Note(kamo): Use '_' instead of '-' as separator.
    # '-' is confusing if written in yaml.
    parser.add_argument(
        "--log_level",
        type=lambda x: x.upper(),
        default="INFO",
        choices=("CRITICAL", "ERROR", "WARNING", "INFO", "DEBUG", "NOTSET"),
        help="The verbose level of logging",
    )

    parser.add_argument("--output_dir", type=str, required=True)
    parser.add_argument(
        "--ngpu",
        type=int,
        default=0,
        help="The number of gpus. 0 indicates CPU mode",
    )
    parser.add_argument(
        "--njob",
        type=int,
        default=1,
        help="The number of jobs for each gpu",
    )
    parser.add_argument(
        "--gpuid_list",
        type=str,
        default="",
        help="The visible gpus",
    )
    parser.add_argument("--seed", type=int, default=0, help="Random seed")
    parser.add_argument(
        "--dtype",
        default="float32",
        choices=["float16", "float32", "float64"],
        help="Data type",
    )
    parser.add_argument(
        "--num_workers",
        type=int,
        default=1,
        help="The number of workers used for DataLoader",
    )

    group = parser.add_argument_group("Input data related")
    group.add_argument(
        "--data_path_and_name_and_type",
        type=str2triple_str,
        required=True,
        action="append",
    )
    group.add_argument("--key_file", type=str_or_none)
    parser.add_argument(
        "--hotword",
        type=str_or_none,
        default=None,
        help="hotword file path or hotwords seperated by space"
    )
    group.add_argument("--allow_variable_data_keys", type=str2bool, default=False)
    group.add_argument(
        "--mc",
        type=bool,
        default=False,
        help="MultiChannel input",
    )

    group = parser.add_argument_group("The model configuration related")
    group.add_argument(
        "--vad_infer_config",
        type=str,
        help="VAD infer configuration",
    )
    group.add_argument(
        "--vad_model_file",
        type=str,
        help="VAD model parameter file",
    )
    group.add_argument(
        "--cmvn_file",
        type=str,
        help="Global CMVN file",
    )
    group.add_argument(
        "--asr_train_config",
        type=str,
        help="ASR training configuration",
    )
    group.add_argument(
        "--asr_model_file",
        type=str,
        help="ASR model parameter file",
    )
    group.add_argument(
        "--lm_train_config",
        type=str,
        help="LM training configuration",
    )
    group.add_argument(
        "--lm_file",
        type=str,
        help="LM parameter file",
    )
    group.add_argument(
        "--word_lm_train_config",
        type=str,
        help="Word LM training configuration",
    )
    group.add_argument(
        "--word_lm_file",
        type=str,
        help="Word LM parameter file",
    )
    group.add_argument(
        "--ngram_file",
        type=str,
        help="N-gram parameter file",
    )
    group.add_argument(
        "--model_tag",
        type=str,
        help="Pretrained model tag. If specify this option, *_train_config and "
             "*_file will be overwritten",
    )
    group.add_argument(
        "--beam_search_config",
        default={},
        help="The keyword arguments for transducer beam search.",
    )

    group = parser.add_argument_group("Beam-search related")
    group.add_argument(
        "--batch_size",
        type=int,
        default=1,
        help="The batch size for inference",
    )
    group.add_argument("--nbest", type=int, default=5, help="Output N-best hypotheses")
    group.add_argument("--beam_size", type=int, default=20, help="Beam size")
    group.add_argument("--penalty", type=float, default=0.0, help="Insertion penalty")
    group.add_argument(
        "--maxlenratio",
        type=float,
        default=0.0,
        help="Input length ratio to obtain max output length. "
             "If maxlenratio=0.0 (default), it uses a end-detect "
             "function "
             "to automatically find maximum hypothesis lengths."
             "If maxlenratio<0.0, its absolute value is interpreted"
             "as a constant max output length",
    )
    group.add_argument(
        "--minlenratio",
        type=float,
        default=0.0,
        help="Input length ratio to obtain min output length",
    )
    group.add_argument(
        "--ctc_weight",
        type=float,
        default=0.0,
        help="CTC weight in joint decoding",
    )
    group.add_argument("--lm_weight", type=float, default=1.0, help="RNNLM weight")
    group.add_argument("--ngram_weight", type=float, default=0.9, help="ngram weight")
    group.add_argument("--streaming", type=str2bool, default=False)
    group.add_argument("--simu_streaming", type=str2bool, default=False)
    group.add_argument("--chunk_size", type=int, default=16)
    group.add_argument("--left_context", type=int, default=16)
    group.add_argument("--right_context", type=int, default=0)
    group.add_argument(
        "--display_partial_hypotheses",
        type=bool,
        default=False,
        help="Whether to display partial hypotheses during chunk-by-chunk inference.",
    )

    group = parser.add_argument_group("Dynamic quantization related")
    group.add_argument(
        "--quantize_asr_model",
        type=bool,
        default=False,
        help="Apply dynamic quantization to ASR model.",
    )
    group.add_argument(
        "--quantize_modules",
        nargs="*",
        default=None,
        help="""Module names to apply dynamic quantization on.
        The module names are provided as a list, where each name is separated
        by a comma (e.g.: --quantize-config=[Linear,LSTM,GRU]).
        Each specified name should be an attribute of 'torch.nn', e.g.:
        torch.nn.Linear, torch.nn.LSTM, torch.nn.GRU, ...""",
    )
    group.add_argument(
        "--quantize_dtype",
        type=str,
        default="qint8",
        choices=["float16", "qint8"],
        help="Dtype for dynamic quantization.",
    )

    group = parser.add_argument_group("Text converter related")
    group.add_argument(
        "--token_type",
        type=str_or_none,
        default=None,
        choices=["char", "bpe", None],
        help="The token type for ASR model. "
             "If not given, refers from the training args",
    )
    group.add_argument(
        "--bpemodel",
        type=str_or_none,
        default=None,
        help="The model path of sentencepiece. "
             "If not given, refers from the training args",
    )
    group.add_argument("--token_num_relax", type=int, default=1, help="")
    group.add_argument("--decoding_ind", type=int, default=0, help="")
    group.add_argument("--decoding_mode", type=str, default="model1", help="")
    group.add_argument(
        "--ctc_weight2",
        type=float,
        default=0.0,
        help="CTC weight in joint decoding",
    )
    return parser


def inference(kwargs):
    assert check_argument_types()
    ncpu = kwargs.get("ncpu", 1)
    torch.set_num_threads(ncpu)

    if kwargs.get("word_lm_train_config", 1) is not None:
        raise NotImplementedError("Word LM is not implemented")
    if kwargs.get("ngpu", 1) > 1:
        raise NotImplementedError("only single GPU decoding is supported")

    for handler in logging.root.handlers[:]:
        logging.root.removeHandler(handler)

    logging.basicConfig(
        level=kwargs["log_level"],
        format="%(asctime)s (%(module)s:%(lineno)d) %(levelname)s: %(message)s",
    )

    if kwargs.get("ngpu", 1) >= 1 and torch.cuda.is_available():
        device = "cuda"
    else:
        device = "cpu"

    # 1. Set random-seed
    set_all_random_seed(kwargs["seed"])

    # 2. Build speech2output
    speech2output = build_speech2output(kwargs)



def main(cmd=None):
    print(get_commandline_args(), file=sys.stderr)
    parser = get_parser()
    parser.add_argument(
        "--mode",
        type=str,
        default="asr",
        help="The decoding mode",
    )
    parser.add_argument(
        "--task_name",
        type=str,
        default="asr",
        help="The decoding mode",
    )
    args = parser.parse_args(cmd)
    kwargs = vars(args)
    kwargs.pop("config", None)

    # set logging messages
    logging.basicConfig(
        level=args.log_level,
        format="%(asctime)s (%(module)s:%(lineno)d) %(levelname)s: %(message)s",
    )
    logging.info("Decoding args: {}".format(kwargs))

    # gpu setting
    if args.ngpu > 0:
        jobid = int(args.output_dir.split(".")[-1])
        gpuid = args.gpuid_list.split(",")[(jobid - 1) // args.njob]
        os.environ["CUDA_DEVICE_ORDER"] = "PCI_BUS_ID"
        os.environ["CUDA_VISIBLE_DEVICES"] = gpuid

    inference_pipeline = inference(kwargs)
    return inference_pipeline(kwargs["data_path_and_name_and_type"], hotword=kwargs.get("hotword", None))


if __name__ == "__main__":
    main()
