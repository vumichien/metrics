# Copyright The PyTorch Lightning team.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
from collections import namedtuple
from functools import partial

import pytest
import torch

from tests.helpers import seed_all
from tests.helpers.testers import BATCH_SIZE, NUM_BATCHES, MetricTester
from torchmetrics.functional.image.sam import spectral_angle_mapper
from torchmetrics.image.sam import SpectralAngleMapper

seed_all(42)

Input = namedtuple("Input", ["preds", "target"])

_inputs = []
for size, channel, dtype in [
    (12, 3, torch.float),
    (13, 3, torch.float32),
    (14, 3, torch.double),
    (15, 3, torch.float64),
]:
    preds = torch.rand(NUM_BATCHES, BATCH_SIZE, channel, size, size, dtype=dtype)
    target = torch.rand(NUM_BATCHES, BATCH_SIZE, channel, size, size, dtype=dtype)
    _inputs.append(Input(preds=preds, target=target))


def _sk_sam(preds, target, reduction):
    # reshape to (batch_size, channel, height*width)
    B, C, H, W = preds.shape
    sk_preds = preds.reshape(B, C, H * W)
    sk_target = target.reshape(B, C, H * W)
    # compute arccos of cosine similarity
    dot_product = (sk_preds * sk_target).sum(dim=1)
    preds_norm = sk_preds.norm(dim=1)
    target_norm = sk_target.norm(dim=1)
    similarity = torch.clamp(dot_product / (preds_norm * target_norm), -1, 1)
    sam_score = similarity.arccos()
    # reduction
    if reduction == "sum":
        to_return = torch.sum(sam_score)
    elif reduction == "elementwise_mean":
        to_return = torch.mean(sam_score)
    else:
        to_return = sam_score
    return to_return


@pytest.mark.parametrize("reduction", ["sum", "elementwise_mean"])
@pytest.mark.parametrize(
    "preds, target",
    [(i.preds, i.target) for i in _inputs],
)
class TestSpectralAngleMapper(MetricTester):
    @pytest.mark.parametrize("ddp", [True, False])
    @pytest.mark.parametrize("dist_sync_on_step", [True, False])
    def test_sam(self, reduction, preds, target, ddp, dist_sync_on_step):
        self.run_class_metric_test(
            ddp,
            preds,
            target,
            SpectralAngleMapper,
            partial(_sk_sam, reduction=reduction),
            dist_sync_on_step,
            metric_args=dict(reduction=reduction),
        )

    def test_sam_functional(self, reduction, preds, target):
        self.run_functional_metric_test(
            preds,
            target,
            spectral_angle_mapper,
            partial(_sk_sam, reduction=reduction),
            metric_args=dict(reduction=reduction),
        )

    # SAM half + cpu does not work due to missing support in torch.log
    @pytest.mark.xfail(reason="SAM metric does not support cpu + half precision")
    def test_sam_half_cpu(self, reduction, preds, target):
        self.run_precision_test_cpu(
            preds,
            target,
            SpectralAngleMapper,
            spectral_angle_mapper,
        )

    @pytest.mark.skipif(not torch.cuda.is_available(), reason="test requires cuda")
    def test_sam_half_gpu(self, reduction, preds, target):
        self.run_precision_test_gpu(preds, target, SpectralAngleMapper, spectral_angle_mapper)


def test_error_on_different_shape(metric_class=SpectralAngleMapper):
    metric = metric_class()
    with pytest.raises(RuntimeError):
        metric(torch.randn([1, 3, 16, 16]), torch.randn([1, 1, 16, 16]))


def test_error_on_invalid_shape(metric_class=SpectralAngleMapper):
    metric = metric_class()
    with pytest.raises(ValueError):
        metric(torch.randn([3, 16, 16]), torch.randn([3, 16, 16]))


def test_error_on_invalid_type(metric_class=SpectralAngleMapper):
    metric = metric_class()
    with pytest.raises(TypeError):
        metric(torch.randn([3, 16, 16]), torch.randn([3, 16, 16], dtype=torch.float64))


def test_error_on_grayscale_image(metric_class=SpectralAngleMapper):
    metric = metric_class()
    with pytest.raises(ValueError):
        metric(torch.randn([16, 1, 16, 16]), torch.randn([16, 1, 16, 16]))
