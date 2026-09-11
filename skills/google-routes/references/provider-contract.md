# Google Routes provider contract 檢查點

本頁只記錄 adapter 的查閱入口與目前採用的最小邊界。Google 的 quota、價格、支援
地區與 API contract 會變動；首次發布或 adapter 改變時重新檢查官方文件並記錄日期。

2026-09-12 查閱結果：

- [Compute Routes](https://developers.google.com/maps/documentation/routes/compute_route_directions)
  使用 `POST https://routes.googleapis.com/directions/v2:computeRoutes`，並以
  `X-Goog-Api-Key` 與 `X-Goog-FieldMask` header 提供認證和 field mask。
- [Waypoint](https://developers.google.com/maps/documentation/routes/reference/rest/v2/Waypoint)
  的 `address`、`placeId` 與 `location` 是同層互斥欄位；本 Skill v1 只公開前兩者。
- [RoutingPreference](https://developers.google.com/maps/documentation/routes/reference/rest/v2/RoutingPreference)
  定義 `TRAFFIC_AWARE` 與 `TRAFFIC_AWARE_OPTIMAL`。
- [TrafficModel](https://developers.google.com/maps/documentation/routes/reference/rest/v2/TrafficModel)
  僅適用於 `DRIVE` 搭配 `TRAFFIC_AWARE_OPTIMAL`；v1 使用 `BEST_GUESS`。
- [Route response](https://developers.google.com/maps/documentation/routes/understand-route-response)
  提供 route、warnings、fallback 與地址解析後的 Place ID；adapter 只保留 summary
  contract 所需欄位。
- [Usage and billing](https://developers.google.com/maps/documentation/routes/usage-and-billing)
  目前列出的 Compute Routes provider 上限為 3,000 QPM；`TRAFFIC_AWARE` 與
  `TRAFFIC_AWARE_OPTIMAL` 會使用 Pro SKU，`TWO_WHEELER` 會使用 Enterprise SKU。
  Skill 的預設 60 QPM 是保守的本機上限，實際費用與 project quota 仍以 Google
  Cloud Console 為準。
- [API key security](https://developers.google.com/maps/api-security-best-practices)
  建議 key 同時採 API restriction 與適用的 application restriction，並放在 source tree
  之外。
