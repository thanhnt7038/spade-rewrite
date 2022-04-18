import torch
from torch import nn
from dataclasses import dataclass
from typing import Optional, List, Dict
from .box import Box
from functools import cache
from transformers import AutoTokenizer as AutoTokenizer_


@dataclass
class SpadeData:
    """Unified model input data

    This struct aims to provide an unified input to the preprocessing
    process. Since difference OCR engine has difference outputs and
    we have yet decided on one, we can just translate each of the OCR
    outputs to this struct and write the preprocessing functionality once.

    Attributes
    ----------
    texts: List[str]
        Texts inside each bounding boxes
    boxes: List[Box]
        List of bounding box in unifed format (see spade.box.Box)
    width: int
        Image width
    height: int
        Image height
    relations: Optional[List]
        List of relation matrices, there could be many relations.
        This is equivalent to the label (which the model have to learn).
        Inference data might not have label.
    """
    texts: List[str]
    boxes: List[Box]
    width: int
    height: int
    relations: Optional[List]


class RelationTagger(nn.Module):
    def __init__(self, n_fields, hidden_size, head_p_dropout=0.1):
        super().__init__()
        self.head = nn.Linear(hidden_size, hidden_size)
        self.tail = nn.Linear(hidden_size, hidden_size)
        self.field_embeddings = nn.Parameter(
            torch.rand(1, n_fields, hidden_size))
        self.W_label_0 = nn.Linear(hidden_size, hidden_size, bias=False)
        self.W_label_1 = nn.Linear(hidden_size, hidden_size, bias=False)

    def forward(self, enc):

        enc_head = self.head(enc)
        enc_tail = self.tail(enc)

        batch_size = enc_tail.size(0)
        field_embeddings = self.field_embeddings.expand(batch_size, -1, -1)
        enc_head = torch.cat([field_embeddings, enc_head], dim=1)

        score_0 = torch.matmul(
            enc_head, self.W_label_0(enc_tail).transpose(1, 2))
        score_1 = torch.matmul(
            enc_head, self.W_label_1(enc_tail).transpose(1, 2))

        return torch.cat([score_0.unsqueeze(1), score_1.unsqueeze(1)], dim=1)


class SpadeLoss(nn.Module):
    def __init__(self, num_fields, weight=[0.1, 1]):
        super().__init__()
        weight = torch.tensor(weight)
        self.loss = nn.CrossEntropyLoss(weight=weight)
        self.num_fields = num_fields

    def true_length(self, mask):
        batch = len(mask.shape) == 2
        if batch:
            return [self.true_length(m) for m in mask]
        return torch.where(mask == 1)[-1][-1]

    def forward(self, relations, labels, input_masks=None):
        bsz, n, i, j = relations.shape
        bsz, i1, j1 = labels.shape
        assert i == i1
        assert j == j1
        # lf = nn.CrossEntropyLoss()
        if input_masks is not None:
            true_lengths = self.true_length(input_masks)
        else:
            true_lengths = [j for _ in range(bsz)]
        loss = 0
        labels = labels.type(torch.long)
        for b in range(bsz):
            nc = true_lengths[b]
            nr = nc + self.num_fields
            loss += self.loss(relations[b: b + 1, :, :nr, :nc],
                              labels[b: b + 1, :nr, :nc])
            # loss += lf(rel[b : b + 1], labels[b : b + 1])
        return loss


@cache
def AutoTokenizer(*args, **kwargs):
    """Return a pretrained tokenizer

    This function is the cached version of AutoTokenizer counter part.
    """
    return AutoTokenizer_.from_pretrained(*args, **kwargs)


def preprocess(config: Dict,
               data: SpadeData):
    #
    texts = data.texts
    boxes = data.boxes
    width = data.width
    height = data.height
