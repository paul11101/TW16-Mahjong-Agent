"""整合端錯誤碼：全部集中在這裡，對應 docs/integration/w4_notes.md 第 4 節。

舊的 import 路徑仍可用（action_executor / verifier / discard_executor / pipeline 都會 re-export），
新的程式請直接從 src.control.errors import。
"""

from __future__ import annotations

# --- ActionReceipt.error_code：映射（點擊前，沒有 UI 動作）---
ERR_UNSUPPORTED_ACTION = "UNSUPPORTED_ACTION"
ERR_TILE_NOT_FOUND = "TILE_NOT_FOUND"
ERR_TILE_OUT_OF_FRAME = "TILE_OUT_OF_FRAME"
ERR_BUTTON_NOT_FOUND = "BUTTON_NOT_FOUND"
ERR_BUTTON_DISABLED = "BUTTON_DISABLED"
ERR_BUTTON_OUT_OF_FRAME = "BUTTON_OUT_OF_FRAME"
ERR_CHOICE_NOT_FOUND = "CHOICE_NOT_FOUND"
ERR_MAPPING = "TILE_MAPPING_ERROR"

# --- ActionReceipt.error_code：安全閘門 ---
ERR_WINDOW_NOT_FOREGROUND = "WINDOW_NOT_FOREGROUND"
ERR_CONTROLLER_NOT_RUNNING = "CONTROLLER_NOT_RUNNING"

# --- ActionReceipt.error_code：點擊後驗證 ---
ERR_ACTION_TIMEOUT = "ACTION_TIMEOUT"  # 逾時仍沒有變化
ERR_ACTION_NOT_STABLE = "ACTION_NOT_STABLE"  # 有變化但沒穩定（動畫未結束）
ERR_FRAME_SIZE_CHANGED = "FRAME_SIZE_CHANGED"  # 擷取大小變了（視窗縮放／移動）
ERR_CAPTURE_FAILED = "CAPTURE_FAILED"  # 擷取不到畫面

# --- TurnResult.error（沒有回執的情況）---
ERR_NO_LEGAL_ACTIONS = "NO_LEGAL_ACTIONS"
ERR_NO_REACTION_TARGET = "NO_REACTION_TARGET"

# --- 整合層：狀態一致性／低信心（W5）---
ERR_STATE_MISMATCH = "STATE_MISMATCH"
ERR_LOW_CONFIDENCE = "LOW_CONFIDENCE"

# 驗證失敗時需要立即停止（要重新定位或已無法擷取）的錯誤碼
STOP_ON_VERIFY_ERRORS = (ERR_FRAME_SIZE_CHANGED, ERR_CAPTURE_FAILED)

# --- 整合層：整局流程（W6）---
ERR_TURN_EXCEPTION = "TURN_EXCEPTION"  # 回合函式拋出例外（程式錯誤或策略／規則回傳不合法資料）
ERR_NOT_ADVANCED = "NOT_ADVANCED"  # 動作成功但畫面一直沒有進到下一步，不重複點擊，改暫停
ERR_OBSERVE_FAILED = "OBSERVE_FAILED"  # 連續讀不到畫面／牌桌資訊
ERR_IDLE_TIMEOUT = "IDLE_TIMEOUT"  # 太久沒有輪到自己（卡住或對手當機）
ERR_LAYOUT_STALE = "LAYOUT_STALE"  # 網頁牌框一直不是最新版本（網頁沒重畫完），不點擊、自動重試