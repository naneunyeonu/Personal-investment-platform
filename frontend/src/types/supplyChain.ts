// ── 공급망(밸류체인) 관련 타입 ───────────────────────────────────────────────

export type NodeRiskLevel = 'LOW' | 'MEDIUM' | 'HIGH' | 'CRITICAL'
export type SupplyChainNodeType =
  | 'COMPANY'
  | 'FACTORY'
  | 'PORT'
  | 'LOGISTICS_HUB'
  | 'RAW_MATERIAL_SITE'
  | 'DISTRIBUTION_CENTER'

// ── GeoJSON 타입 (백엔드 /supply-chain/geojson 응답) ─────────────────────

export type GeoJSONCoordinate = [number, number]  // [lon, lat]

export interface GeoJSONPoint {
  type: 'Point'
  coordinates: GeoJSONCoordinate
}

export interface GeoJSONLineString {
  type: 'LineString'
  coordinates: GeoJSONCoordinate[]
}

export interface GeoJSONFeature<G = GeoJSONPoint | GeoJSONLineString> {
  type: 'Feature'
  geometry: G | null
  properties: Record<string, unknown>
}

export interface GeoJSONFeatureCollection {
  type: 'FeatureCollection'
  features: GeoJSONFeature[]
  total_nodes: number
  total_edges: number
}

// ── 노드 속성 (properties 내부) ─────────────────────────────────────────

export interface NodeProperties {
  node_id: string
  name: string
  ticker: string | null
  node_type: SupplyChainNodeType
  country_code: string
  city: string | null
  industry_sector: string | null
  risk_level: NodeRiskLevel
  risk_note: string | null
}

export interface EdgeProperties {
  edge_id: string
  source_node_id: string
  target_node_id: string
  relation_type: string
  dependency_score: number
  annual_value_usd: number | null
}

// ── 지정학적 리스크 분석 ──────────────────────────────────────────────────

export interface GeopoliticalRiskRequest {
  news_text: string
  portfolio_tickers: string[]
  question?: string
}

export interface AffectedNodeInfo {
  node_id: string | null
  node_name: string
  ticker: string | null
  country_code: string | null
  impact_type: string
  impact_severity: string
  impact_description: string
}

export interface GeopoliticalRiskResponse {
  task_id: string
  event_summary: string
  affected_nodes: AffectedNodeInfo[]
  ripple_summary: string
  portfolio_impact: string
  raw_report: string
  usage: Record<string, number>
}

// ── 리스크 레벨 색상 매핑 ────────────────────────────────────────────────

export const RISK_COLORS: Record<NodeRiskLevel, string> = {
  LOW: '#4CAF50',
  MEDIUM: '#FF9800',
  HIGH: '#F44336',
  CRITICAL: '#9C27B0',
}
