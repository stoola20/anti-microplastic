# D3 對照矩陣：claude-sonnet-5 vs gpt-5.6-terra

- Claude 來源：`evals/results/baseline-2026-09-15T01-19-05-sonnet-5.jsonl`
- OpenAI 來源：`evals/results/baseline-2026-09-15T02-50-41-gpt-5.6-terra.jsonl`
- 兩邊都是 10 案例 × 3 次，0 錯誤 0 跳過

| case | claude 延遲(s) | openai 延遲(s) | claude in_tok | openai in_tok | claude out_tok | openai out_tok | claude checks | openai checks |
|---|---:|---:|---:|---:|---:|---:|---|---|
| A1 | 28.96 | 20.45 | 26250 | 19213 | 1444 | 1218 | basic_shape=3/3 | basic_shape=3/3 |
| A2 | 26.31 | 15.40 | 12847 | 12906 | 1446 | 904 | basic_shape=3/3 | basic_shape=3/3 |
| A3 | 42.61 | 30.85 | 35100 | 30147 | 2282 | 1395 | basic_shape=3/3 | basic_shape=3/3 |
| B1 | 25.54 | 20.87 | 10346 | 12094 | 1366 | 1264 | basic_shape=3/3 | basic_shape=3/3 |
| B2 | 24.46 | 15.99 | 10159 | 7735 | 1277 | 1062 | basic_shape=3/3 | basic_shape=3/3 |
| B3 | 19.20 | 12.12 | 10474 | 8462 | 971 | 763 | basic_shape=3/3 | basic_shape=3/3 |
| C1 | 25.62 | 18.90 | 10304 | 7755 | 1413 | 1246 | basic_shape=3/3 | basic_shape=3/3 |
| C2 | 22.67 | 11.77 | 12870 | 12627 | 1159 | 646 | basic_shape=3/3 | basic_shape=3/3 |
| D1 | 0.00 | 1.18 | - | - | - | - | state_roundtrip_match=3/3 | state_roundtrip_match=3/3 |
| D2 | 16.99 | 10.10 | 16462 | 10764 | 848 | 462 | basic_shape=3/3, equals_not_found=0/3 | basic_shape=3/3, equals_not_found=0/3 |

## 觀察

- **D2 NOT_FOUND fallback 在兩個平台都沒有被觸發**（Claude 0/3、OpenAI 0/3 命中 `equals_not_found`）：兩邊模型都選擇自然語言回覆「查不到」，而不是走到寫死的 `NOT_FOUND_BRIEF`/`NOT_FOUND_FULL` 常數。`basic_shape` 兩邊都是 3/3，代表自然語言回覆本身格式正確——這個 fallback 常數在實測中形同 dead code，不是 OpenAI 路徑特有的問題。
- **D1（「詳細」讀取）延遲：Claude 0.00s vs OpenAI 1.18s**——Claude 的 `state.py` 是純記憶體查表，OpenAI 路徑要打一次 `responses.retrieve()`。這不是生成成本，是這次設計刻意的取捨：本地只存一個 id，換回全文要付一次網路延遲。
- **生成延遲（排除 D1）：Claude 平均 25.82s vs OpenAI 平均 17.38s**——這次測到的 9 個生成案例，gpt-5.6-terra 全部比 claude-sonnet-5 快，且 input/output token 用量也普遍較低（樣本數小，N=3，僅供這次 PoC 對照參考，不是嚴謹的統計結論）。
