# 使用固定順序且數量受限的中途停靠點

`google-routes` query schema v2 以 2–12 個 Named Route Points 表示一筆 Fixed-order Itinerary：
第一點映射為 origin、最後一點映射為 destination，中間最多 10 點映射為 Google
`intermediates` stopovers。adapter 保持使用者順序，不設定 `optimizeWaypointOrder`，並將 Google
route legs 正規化為不含地址的 `itinerary_summary`。query v1 與 `summary` profile 保持相容。

Google 支援更多 intermediate waypoints 與自動最佳化，但 11 個以上中途點及 waypoint optimization
可能改變 SKU；最佳化也會改變使用者明確提供的順序。第一階段選擇最多 10 個固定順序 stopovers，
讓成本、語意與測試維持可預期。未來若有超過 10 點或重新排序的實際需求，應以新的 schema／profile
明確揭露成本與順序語意，不擴張既有契約。
