import torch
from torch import Tensor, nn
from .action_mask import ACTION_SPACE_SIZE
from .feature_spec import FEATURE_SIZE

class VlogBCExecutor(nn.Module):
    def __init__(self):
        super().__init__()
        self.feature_size = FEATURE_SIZE
        # 把決策玩家可見的 555 維特徵編碼成 256 維表示
        self.encoder = nn.Sequential(
            nn.Linear(FEATURE_SIZE, 256), nn.ReLU(),
            nn.Linear(256, 256), nn.ReLU(),
        )
        # 從牌局表示估計 128 維潛在分布的平均值與對數標準差
        self.prior_mean = nn.Linear(256, 128)
        self.prior_log_std = nn.Linear(256, 128)
        self.action_head = nn.Sequential(
            nn.Linear(128, 256), nn.ReLU(),
            nn.Linear(256, 256), nn.ReLU(),
            nn.Linear(256, ACTION_SPACE_SIZE),
        )

    def forward(self, features: Tensor) -> Tensor:
        if features.dim() != 2 or features.size(1) != self.feature_size:
            raise ValueError("expected features or shape [B, 555]")

        if features.dtype != torch.float32:
            raise ValueError("expected float32 features")

        hidden = self.encoder(features)
        latent = self.prior_mean(hidden)

        # 訓練時依分布取樣，評估時直接使用平均值，讓同一牌面得到相同分數
        if self.training:
            log_std = (self.prior_log_std(hidden) - 1.0).clamp(-10.0, 2.0)
            latent = latent + torch.randn_like(latent) * log_std.exp()

        # 輸出 125 個動作的原始分數，合法動作遮罩由呼叫端套用
        return self.action_head(latent)
