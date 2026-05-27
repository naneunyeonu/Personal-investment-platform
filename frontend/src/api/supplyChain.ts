import { api } from './client'
import type {
  GeoJSONFeatureCollection,
  GeopoliticalRiskRequest,
} from '../types/supplyChain'

/** 공급망 GeoJSON FeatureCollection — Mapbox/Leaflet 지도 렌더링용 */
export const getSupplyChainGeoJSON = (
  tickers?: string[],
  includeEdges = true,
): Promise<GeoJSONFeatureCollection> => {
  const params: Record<string, unknown> = { include_edges: includeEdges }
  if (tickers?.length) params.tickers = tickers.join(',')
  return api.get<GeoJSONFeatureCollection>('/supply-chain/geojson', { params }).then(r => r.data)
}

/** 지정학적 리스크 분석 요청 → task_id 반환 (Celery 비동기) */
export const analyzeGeopoliticalRisk = (
  data: GeopoliticalRiskRequest,
): Promise<{ task_id: string; message: string }> =>
  api.post('/supply-chain/risk-analysis', data).then(r => r.data)
