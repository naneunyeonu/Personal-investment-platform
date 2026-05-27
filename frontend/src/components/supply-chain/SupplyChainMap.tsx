/**
 * SupplyChainMap — 공급망 노드·에지 Leaflet 지도 시각화
 *
 * 백엔드 GET /supply-chain/geojson 응답을 Leaflet GeoJSON 레이어로 렌더링.
 *
 * 노드(Point):
 *   - 리스크 레벨에 따른 색상 원형 마커 (LOW=초록, MEDIUM=주황, HIGH=빨강, CRITICAL=보라)
 *   - 클릭 시 팝업: 이름, 티커, 국가, 섹터, 리스크 메모
 *
 * 에지(LineString):
 *   - dependency_score 비례 선 두께 (1~5px)
 *   - 클릭 시 팝업: 관계 유형, 의존도 점수
 */

import { useEffect, useRef, useState } from 'react'
import L from 'leaflet'
import 'leaflet/dist/leaflet.css'

import { getSupplyChainGeoJSON } from '../../api/supplyChain'
import type {
  GeoJSONFeatureCollection,
  NodeProperties,
  EdgeProperties,
  NodeRiskLevel,
} from '../../types/supplyChain'
import { RISK_COLORS } from '../../types/supplyChain'

// ── Leaflet 기본 마커 아이콘 경로 수정 (Vite 번들 이슈) ───────────────────
delete (L.Icon.Default.prototype as unknown as Record<string, unknown>)._getIconUrl
L.Icon.Default.mergeOptions({
  iconRetinaUrl: new URL('leaflet/dist/images/marker-icon-2x.png', import.meta.url).href,
  iconUrl:       new URL('leaflet/dist/images/marker-icon.png',   import.meta.url).href,
  shadowUrl:     new URL('leaflet/dist/images/marker-shadow.png', import.meta.url).href,
})

// ── 리스크 레벨 → 원형 마커 생성 ─────────────────────────────────────────

function makeCircleMarker(risk: NodeRiskLevel): L.DivIcon {
  const color = RISK_COLORS[risk]
  return L.divIcon({
    className: '',
    html: `<div style="
      width:14px; height:14px;
      border-radius:50%;
      background:${color};
      border:2px solid rgba(255,255,255,0.8);
      box-shadow:0 0 6px ${color}88;
    "></div>`,
    iconSize: [14, 14],
    iconAnchor: [7, 7],
    popupAnchor: [0, -10],
  })
}

// ── Props ─────────────────────────────────────────────────────────────────

interface Props {
  tickers?: string[]
  includeEdges?: boolean
}

// ── 컴포넌트 ──────────────────────────────────────────────────────────────

export default function SupplyChainMap({ tickers, includeEdges = true }: Props) {
  const mapRef     = useRef<HTMLDivElement>(null)
  const leafletRef = useRef<L.Map | null>(null)
  const geoLayRef  = useRef<L.GeoJSON | null>(null)

  const [geoData, setGeoData]   = useState<GeoJSONFeatureCollection | null>(null)
  const [loading, setLoading]   = useState(true)
  const [error, setError]       = useState<string | null>(null)

  // ── 지도 초기화 ──────────────────────────────────────────────────────

  useEffect(() => {
    if (!mapRef.current || leafletRef.current) return

    leafletRef.current = L.map(mapRef.current, {
      center: [25, 100],   // 아시아 중심
      zoom: 3,
      zoomControl: true,
    })

    // OpenStreetMap 타일 레이어 (다크 스타일)
    L.tileLayer('https://{s}.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}{r}.png', {
      attribution: '&copy; <a href="https://carto.com/">CARTO</a>',
      subdomains: 'abcd',
      maxZoom: 19,
    }).addTo(leafletRef.current)

    return () => {
      leafletRef.current?.remove()
      leafletRef.current = null
    }
  }, [])

  // ── 데이터 불러오기 ─────────────────────────────────────────────────

  useEffect(() => {
    setLoading(true)
    setError(null)
    getSupplyChainGeoJSON(tickers, includeEdges)
      .then(data => setGeoData(data))
      .catch(() => setError('공급망 데이터를 불러오지 못했습니다.'))
      .finally(() => setLoading(false))
  }, [tickers, includeEdges])

  // ── GeoJSON → Leaflet 레이어 렌더링 ─────────────────────────────────

  useEffect(() => {
    const map = leafletRef.current
    if (!map || !geoData) return

    // 기존 레이어 제거
    if (geoLayRef.current) {
      map.removeLayer(geoLayRef.current)
    }

    geoLayRef.current = L.geoJSON(geoData as unknown as GeoJSON.FeatureCollection, {

      // 노드(Point) → 리스크 색상 원형 마커
      pointToLayer: (feature, latlng) => {
        const props = feature.properties as NodeProperties
        const marker = L.marker(latlng, {
          icon: makeCircleMarker(props.risk_level),
        })

        const popupHtml = `
          <div style="font-size:13px; line-height:1.6; min-width:160px">
            <strong>${props.name}</strong>
            ${props.ticker ? `<span style="color:#94a3b8"> (${props.ticker})</span>` : ''}
            <hr style="border-color:#334155; margin:6px 0"/>
            <div>🌐 ${props.country_code}${props.city ? ` · ${props.city}` : ''}</div>
            ${props.industry_sector ? `<div>🏭 ${props.industry_sector}</div>` : ''}
            <div>
              <span style="
                display:inline-block; padding:1px 6px;
                border-radius:4px; font-size:11px; font-weight:600;
                background:${RISK_COLORS[props.risk_level]}33;
                color:${RISK_COLORS[props.risk_level]};
                border:1px solid ${RISK_COLORS[props.risk_level]}66;
              ">${props.risk_level}</span>
            </div>
            ${props.risk_note ? `<div style="color:#94a3b8; font-size:11px; margin-top:4px">${props.risk_note}</div>` : ''}
          </div>
        `
        marker.bindPopup(popupHtml)
        return marker
      },

      // 에지(LineString) → 의존도 비례 선
      style: (feature) => {
        if (feature?.geometry.type !== 'LineString') return {}
        const props = feature.properties as EdgeProperties
        const score = props.dependency_score ?? 0.5
        return {
          color: '#60a5fa',        // blue-400
          weight: Math.max(1, Math.round(score * 5)),
          opacity: 0.55 + score * 0.3,
          dashArray: score < 0.4 ? '6 4' : undefined,
        }
      },

      // 에지 팝업
      onEachFeature: (feature, layer) => {
        if (feature.geometry.type !== 'LineString') return
        const props = feature.properties as EdgeProperties
        layer.bindPopup(
          `<div style="font-size:12px">
            <div><strong>${props.relation_type}</strong></div>
            <div>의존도: <strong>${(props.dependency_score * 100).toFixed(0)}%</strong></div>
            ${props.annual_value_usd
              ? `<div>연간 거래액: $${(props.annual_value_usd / 1e6).toFixed(1)}M</div>`
              : ''
            }
          </div>`
        )
      },
    }).addTo(map)

    // 노드가 있으면 전체 뷰로 핏
    if (geoData.total_nodes > 0) {
      try {
        const bounds = geoLayRef.current!.getBounds()
        if (bounds.isValid()) map.fitBounds(bounds, { padding: [40, 40] })
      } catch {
        // 빈 레이어 bounds 오류 무시
      }
    }
  }, [geoData])

  // ── 렌더링 ───────────────────────────────────────────────────────────

  return (
    <div className="relative w-full h-full rounded-xl overflow-hidden border border-slate-700">

      {/* 지도 컨테이너 */}
      <div ref={mapRef} className="w-full h-full" />

      {/* 로딩 오버레이 */}
      {loading && (
        <div className="absolute inset-0 flex items-center justify-center
                        bg-slate-900/70 backdrop-blur-sm z-[1000]">
          <div className="flex flex-col items-center gap-3">
            <div className="w-8 h-8 border-4 border-blue-500 border-t-transparent
                            rounded-full animate-spin" />
            <span className="text-slate-300 text-sm">공급망 데이터 불러오는 중…</span>
          </div>
        </div>
      )}

      {/* 에러 오버레이 */}
      {error && !loading && (
        <div className="absolute inset-0 flex items-center justify-center
                        bg-slate-900/80 z-[1000]">
          <div className="text-center space-y-3">
            <p className="text-red-400">{error}</p>
            <button
              onClick={() => {
                setError(null)
                setLoading(true)
                getSupplyChainGeoJSON(tickers, includeEdges)
                  .then(setGeoData)
                  .catch(() => setError('공급망 데이터를 불러오지 못했습니다.'))
                  .finally(() => setLoading(false))
              }}
              className="px-4 py-2 rounded-lg bg-blue-600 hover:bg-blue-700
                         text-white text-sm transition-colors"
            >
              재시도
            </button>
          </div>
        </div>
      )}

      {/* 리스크 범례 */}
      {!loading && !error && (
        <div className="absolute bottom-4 left-4 z-[999]
                        bg-slate-900/90 border border-slate-700 rounded-lg p-3
                        backdrop-blur-sm">
          <p className="text-xs font-semibold text-slate-400 mb-2 uppercase tracking-wide">
            리스크 레벨
          </p>
          {(Object.entries(RISK_COLORS) as [NodeRiskLevel, string][]).map(([level, color]) => (
            <div key={level} className="flex items-center gap-2 text-xs text-slate-300 mb-1">
              <div
                className="w-3 h-3 rounded-full border border-white/30"
                style={{ backgroundColor: color }}
              />
              {level}
            </div>
          ))}
          {geoData && (
            <p className="text-xs text-slate-500 mt-2 border-t border-slate-700 pt-2">
              노드 {geoData.total_nodes}개 · 에지 {geoData.total_edges}개
            </p>
          )}
        </div>
      )}
    </div>
  )
}
