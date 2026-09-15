"""Tier-1 baseline eval case definitions.

案例定義釘選後不應隨意更動（除了 D2 的暫定測試字串，見下方註記），
以確保多次 run 之間的結果可以互相比較。cases_fingerprint（見 harness.py）
會偵測這份檔案是否被改過。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

IMAGES_DIR = Path(__file__).parent / "fixtures" / "images"


@dataclass(frozen=True)
class EvalCase:
    case_id: str
    category: str  # "A" / "B" / "C" / "D"
    call_target: str  # "analyze_image" / "analyze_product_name" / "state_roundtrip"
    purpose: str
    text_input: str | None = None
    image_path: Path | None = None
    depends_on: str | None = None  # D1 用："B1"
    hard_checks: tuple[str, ...] = field(default_factory=lambda: ("basic_shape",))


CASES: list[EvalCase] = [
    EvalCase(
        case_id="A1",
        category="A",
        call_target="analyze_product_name",
        purpose="知名產品，text search grounding",
        text_input="理膚寶水 B5 精華",
    ),
    EvalCase(
        case_id="A2",
        category="A",
        call_target="analyze_image",
        purpose="image input 正確性（個人護理成分標示）",
        image_path=IMAGES_DIR / "a2_personal_care_label.jpg",
    ),
    EvalCase(
        case_id="A3",
        category="A",
        call_target="analyze_product_name",
        purpose="冷門/小眾品牌，搜尋資料稀疏時的品質",
        text_input="朵璽杏仁酸18%",
    ),
    EvalCase(
        case_id="B1",
        category="B",
        call_target="analyze_product_name",
        purpose="知名產品",
        text_input="50嵐紙杯",
    ),
    EvalCase(
        case_id="B2",
        category="B",
        call_target="analyze_product_name",
        purpose="使用情境關鍵字（微波）是否影響風險判斷",
        text_input="PP 保鮮盒微波",
    ),
    EvalCase(
        case_id="B3",
        category="B",
        call_target="analyze_image",
        # 實際照片是網路商品展示照，沒有任何可見的材質標示文字，只有餐具外觀。
        # 這其實比「拍到清楚標示」更貼近真實使用情境——買回家或外食時通常看不到
        # 材質標示，所以這裡刻意測「模型能不能只從外觀判斷美耐皿風險」，
        # 不是像 A2/C2 那樣測「讀懂印刷標示」。
        purpose="高風險物質辨識、image input（食器外觀無材質標示時，模型能否從外觀判斷風險——貼近外食/已購入情境）",
        image_path=IMAGES_DIR / "b3_melamine_tableware.jpg",
    ),
    EvalCase(
        case_id="C1",
        category="C",
        call_target="analyze_product_name",
        purpose="材質比例直接輸入",
        text_input="聚酯 85% 氨綸 15%",
    ),
    EvalCase(
        case_id="C2",
        category="C",
        call_target="analyze_image",
        purpose="image input＋類別 C（衣物材質吊牌）",
        image_path=IMAGES_DIR / "c2_clothing_tag.jpg",
    ),
    EvalCase(
        case_id="D1",
        category="D",
        call_target="state_roundtrip",
        purpose="state.py 存取邏輯（BRIEF→FULL 狀態管理），重用同輪 B1 結果，不額外呼叫 API",
        depends_on="B1",
        hard_checks=("state_roundtrip_match",),
    ),
    EvalCase(
        case_id="D2",
        category="D",
        call_target="analyze_product_name",
        purpose="NOT_FOUND fallback 是否觸發",
        # 暫定字串，僅需確保是不存在的產品；可隨時改，不影響其他案例。
        text_input="測試用不存在產品ABC999號",
        hard_checks=("basic_shape", "equals_not_found"),
    ),
]

CASES_BY_ID: dict[str, EvalCase] = {c.case_id: c for c in CASES}

# 今天可跑（不需要圖片）的文字案例，依 plan 定案順序。
TEXT_CASE_IDS: tuple[str, ...] = ("A1", "A3", "B1", "B2", "C1", "D1", "D2")

# 待補照片才能跑的核心圖片案例。
IMAGE_CASE_IDS: tuple[str, ...] = ("A2", "B3", "C2")
