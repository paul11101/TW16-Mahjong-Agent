# 台灣16張麻將Agent

## 專案簡介

本專題希望建立「看懂畫面、理解牌局、選擇動作、完成操作、驗證結果」的自動對局系統。

第一版：採用可控的台麻測試介面，交付可重現、可量測的完整操作流程。

## 主要功能

- Agent 能只依玩家看得到的畫面，在可控台麻介面連續完成 20 局。
- 主線採 Agony5757/mahjong 的 VLOGMahjong 作模型架構基底；台灣 16 張規則與環境另行適配。

## 台灣16張麻將為何

- 使用完整的136張牌（不含春夏秋冬、梅蘭竹菊一般可算作花牌）。
- 每位玩家發16張牌（通常莊家多一張以便先出牌)。
- 遊戲通常固定4位玩家。

## 建立虛擬環境(不要提交這個資料夾，要先確認資料夾位置)

建立
```bash
python -m venv .venv
```
進入
```bash
.venv\Scripts\Activate
```
離開
```bash
deactivate
```
安裝共通套件
```bash
pip install -r requirements.txt
```
確認安裝
```bash
python -c "import cv2, numpy, torch, fastapi, pydantic, mss, pyautogui, pydantic, uvicorn; print('全成功')"
```
## 分工

[視覺辨識](https://github.com/a0967017679-lab)

[策略與模型](https://github.com/paul11101)

[規則與模擬器](https://github.com/stanly0958006345-creator)

[系統整合與自動操作](https://github.com/luhuanyue)
