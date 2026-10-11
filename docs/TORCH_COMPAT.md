# torch 兼容矩阵与版本包 ABI 策略（关闭待定问题 #4）

> 日期：2026-10-11 ｜ 状态：已定稿（随 CI 打包流水线落地）

## 决策

1. **torch 不进版本包**：torch/torchvision/torchaudio 复用 AutoDL 镜像自带的 CUDA 环境。
   打包时从 ComfyUI requirements.txt 过滤 torch 系依赖（build_comfy_version.sh）。
2. **ABI 显式建模**：包内 venv 的解释器指向构建机基座 Python，**不可跨 ABI 迁移**。
   manifest 与索引新增 `python_abi` 字段；面板安装时校验实例 Python 与之一致，
   不一致给出明确报错（version_not_ready）。构建固定 Python 3.11（AutoDL 主流镜像基座）。
3. **兼容验证**：ComfyUI 官方 requirements.txt 是权威——各版本对 torch 的最低要求随包内
   requirements 声明，镜像 torch ≥ 声明版本即可运行。构建流水线不装 torch，因此 torch
   版本冲突只可能来自「镜像 torch 过旧」，处理方式：索引条目 notes 标注 torch_baseline，
   面板在版本卡片上展示该信息，用户可选升级镜像或选用旧版 ComfyUI。

## 基线矩阵（首发构建清单）

| ComfyUI 版本 | torch 基线（镜像需 ≥） | python_abi | 备注 |
|---|---|---|---|
| 0.3.39（最新） | 2.4.0+cu124 | 3.11 | 首发 |
| 0.3.30 | 2.4.0+cu124 | 3.11 | 稳定版回溯 |
| 0.3.27 | 2.4.0+cu124 | 3.11 | 稳定版回溯 |
| 0.2.x（旧） | 2.3.1+cu121 | 3.11 | 按需补建 |

> 首批打包版本由作者通过 build-versions workflow 手动触发；上表为发布初始清单。

## 流程

```
build-versions.yml（workflow_dispatch，输入版本 JSON 数组）
  → matrix 构建（每版本一个 job）
      → git clone v<tag> → venv（过滤 torch）→ tar.zst → manifest（sha256/size/abi）
  → release job：generate_versions_index.py 合并 manifest → versions-index.json
      → GitHub Release 附 tar.zst + index
面板「刷新索引」→ latest/download/versions-index.json
```

## 已知限制（记录进风险清单）

- 包体积可控的前提是 venv 不含 torch（实测约 400-800MB/版本）。
- ComfyUI 未来某版本若硬性要求更高 torch，用户需升级镜像或在 JupyterLab 手动升级
  venv 内 torch；面板不做 torch 升级（明确范围外）。
