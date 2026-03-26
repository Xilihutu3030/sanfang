const api = require('../../utils/api')
const util = require('../../utils/util')

const ELEV_COLORS = [
  { max: 10, fill: '#08306b40', stroke: '#063363' },
  { max: 20, fill: '#1565c040', stroke: '#0d47a1' },
  { max: 30, fill: '#2196f340', stroke: '#1976d2' },
  { max: 50, fill: '#43a04740', stroke: '#2e7d32' },
  { max: 80, fill: '#8bc34a40', stroke: '#689f38' },
  { max: 120, fill: '#f9a82540', stroke: '#f57f17' },
  { max: 200, fill: '#ef6c0040', stroke: '#e65100' },
  { max: 99999, fill: '#6d4c4140', stroke: '#4e342e' },
]

function getElevColor(e) {
  for (const c of ELEV_COLORS) if (e < c.max) return c
  return ELEV_COLORS[ELEV_COLORS.length - 1]
}

Page({
  data: {
    weather: null,
    hazards: [],
    hazardMarkers: [],
    polyPoints: [],
    polyMarkers: [],
    allMarkers: [],
    polygons: [],
    polylines: [],
    drawing: false,
    drawShape: 'rect',
    tapPoints: [],
    selectedHazardCount: 0,
    mapCenter: { latitude: 23.1291, longitude: 113.2644 },
    judging: false,
    // 新增：地形与潮汐
    showTerrain: true,
    showLowland: true,
    showRiver: true,
    tideData: null,
    demData: null,
    demPolygons: [],
    lowlandPolygons: [],
    selectionPolygon: [],
    riverPolylines: [],
  },

  onLoad() {
    this._locateAndInit()
  },

  async _locateAndInit() {
    // 先尝试定位
    try {
      const res = await new Promise((resolve, reject) => {
        wx.getLocation({
          type: 'gcj02',
          success: resolve,
          fail: reject,
        })
      })
      this.setData({
        mapCenter: { latitude: res.latitude, longitude: res.longitude },
      })
    } catch (e) {
      console.log('定位失败，使用默认位置')
    }
    this.loadWeather()
    this.loadHazards()
    this.loadDEM()
    this.loadTide()
  },

  async loadWeather() {
    try {
      const data = await api.weather.get()
      this.setData({ weather: util.parseWeatherData(data) })
    } catch (e) {
      console.error('气象加载失败', e)
    }
  },

  async loadHazards() {
    try {
      const data = await api.hazards.list()
      const hazards = data.hazards || []
      const hazardMarkers = hazards
        .filter((h) => h.lat && h.lng)
        .map((h, i) => ({
          id: i,
          latitude: h.lat,
          longitude: h.lng,
          title: h.name,
          iconPath: '',
          width: 28,
          height: 28,
          label: {
            content: h.name,
            fontSize: 10,
            color: h.level === '高风险' ? '#dc2626' : '#d97706',
            bgColor: '#ffffff',
            padding: 3,
            borderRadius: 4,
          },
          callout: {
            content: h.name + '\n' + h.type + ' | ' + h.level + '\n高程: ' + h.elevation + 'm',
            fontSize: 12,
            color: '#1e293b',
            bgColor: '#ffffff',
            padding: 8,
            borderRadius: 8,
            display: 'BYCLICK',
          },
        }))
      this.setData({ hazards, hazardMarkers, allMarkers: hazardMarkers })
      // 从隐患点生成河道折线
      this._buildRiverFromHazards(hazards)
    } catch (e) {
      console.error('隐患点加载失败', e)
    }
  },

  // ==================== DEM 地形高程 ====================

  async loadDEM() {
    const c = this.data.mapCenter
    const offset = 0.05
    const bounds = {
      sw_lat: c.latitude - offset,
      sw_lng: c.longitude - offset,
      ne_lat: c.latitude + offset,
      ne_lng: c.longitude + offset,
    }
    try {
      const data = await api.terrain.demGrid(bounds, 8)
      this.setData({ demData: data })
      this._renderTerrainLayers()
    } catch (e) {
      console.error('DEM加载失败', e)
    }
  },

  _renderTerrainLayers() {
    const dem = this.data.demData
    if (!dem) return
    const demPolys = []
    const lowPolys = []
    const { points, grid_size: gs, bounds: b } = dem
    const latS = (b.ne_lat - b.sw_lat) / gs
    const lngS = (b.ne_lng - b.sw_lng) / gs

    for (let i = 0; i < gs; i++) {
      for (let j = 0; j < gs; j++) {
        const idx = i * (gs + 1) + j
        const p = points[idx]
        if (!p) continue
        const e1 = p.elevation
        const e2 = (points[idx + 1] || p).elevation
        const e3 = (points[idx + gs + 1] || p).elevation
        const e4 = (points[idx + gs + 2] || p).elevation
        const avg = (e1 + e2 + e3 + e4) / 4
        const c = getElevColor(avg)

        const cellPoints = [
          { latitude: b.sw_lat + i * latS, longitude: b.sw_lng + j * lngS },
          { latitude: b.sw_lat + i * latS, longitude: b.sw_lng + (j + 1) * lngS },
          { latitude: b.sw_lat + (i + 1) * latS, longitude: b.sw_lng + (j + 1) * lngS },
          { latitude: b.sw_lat + (i + 1) * latS, longitude: b.sw_lng + j * lngS },
        ]

        if (this.data.showTerrain) {
          demPolys.push({
            points: cellPoints,
            strokeColor: c.stroke,
            strokeWidth: 1,
            fillColor: c.fill,
          })
        }

        if (this.data.showLowland && avg < 50) {
          lowPolys.push({
            points: cellPoints,
            strokeColor: avg < 30 ? '#ef4444' : '#f59e0b',
            strokeWidth: 2,
            fillColor: avg < 30 ? '#dc262640' : '#f59e0b30',
            dottedLine: true,
          })
        }
      }
    }

    this.setData({ demPolygons: demPolys, lowlandPolygons: lowPolys })
    this._mergePolygons()
  },

  // ==================== 河道水系 ====================

  _buildRiverFromHazards(hazards) {
    const riverPts = hazards
      .filter(h => h.type === '河道' && h.lat && h.lng)
      .sort((a, b) => a.lng - b.lng)
    const polylines = []
    if (riverPts.length >= 2) {
      polylines.push({
        points: riverPts.map(h => ({ latitude: h.lat, longitude: h.lng })),
        color: '#0ea5e9',
        width: 6,
        arrowLine: true,
      })
    }
    this.setData({ riverPolylines: polylines })
    this._mergePolylines()
  },

  // ==================== 潮汐数据 ====================

  async loadTide() {
    const c = this.data.mapCenter
    try {
      const data = await api.tide.full(c.latitude, c.longitude)
      const tide = data.tide || {}
      const marine = data.marine || {}
      const tc = tide.current || {}
      const mc = marine.current || {}
      this.setData({
        tideData: {
          status: tc.trend_cn || '--',
          level: tc.level != null ? tc.level.toFixed(2) + 'm' : '--',
          waveHeight: mc.wave_height != null ? mc.wave_height + 'm' : '--',
          swellHeight: mc.swell_height != null ? mc.swell_height + 'm' : '--',
          nextHigh: (tide.next_high_tides || [])[0] ? tide.next_high_tides[0].time.replace('T', ' ') : '--',
          marineRisk: (marine.risk || {}).level_cn || '--',
          tideRisk: (tide.risk || {}).level_cn || '--',
        },
      })
    } catch (e) {
      console.error('潮汐数据加载失败', e)
      this.setData({
        tideData: { status: '加载失败', level: '--', waveHeight: '--', swellHeight: '--', nextHigh: '--', marineRisk: '--', tideRisk: '--' },
      })
    }
  },

  refreshTide() {
    this.loadTide()
    wx.showToast({ title: '刷新潮汐数据', icon: 'none' })
  },

  // ==================== 图层控制 ====================

  toggleTerrain() {
    this.setData({ showTerrain: !this.data.showTerrain })
    this._renderTerrainLayers()
  },
  toggleLowland() {
    this.setData({ showLowland: !this.data.showLowland })
    this._renderTerrainLayers()
  },
  toggleRiver() {
    this.setData({ showRiver: !this.data.showRiver })
    this._mergePolylines()
  },

  // ==================== 合并图层数据 ====================

  _mergePolygons() {
    const all = []
      .concat(this.data.showTerrain ? this.data.demPolygons : [])
      .concat(this.data.showLowland ? this.data.lowlandPolygons : [])
      .concat(this.data.selectionPolygon)
    this.setData({ polygons: all })
  },

  _mergePolylines() {
    this.setData({
      polylines: this.data.showRiver ? this.data.riverPolylines : [],
    })
  },

  // ==================== 圈选逻辑 ====================

  switchShape(e) {
    this.setData({ drawShape: e.currentTarget.dataset.shape })
  },

  startDraw() {
    this.setData({ drawing: true, tapPoints: [] })
    const hint = this.data.drawShape === 'rect'
      ? '点击地图选择矩形的两个对角点'
      : '点击地图选择圆心，再点一下确定半径'
    wx.showToast({ title: hint, icon: 'none', duration: 2000 })
  },

  cancelDraw() {
    this.setData({ drawing: false, tapPoints: [] })
  },

  onMapTap(e) {
    if (!this.data.drawing) return
    const { latitude, longitude } = e.detail
    const taps = this.data.tapPoints.concat({ latitude, longitude })

    if (taps.length === 1) {
      const marker = {
        id: 10000, latitude, longitude, width: 20, height: 20, iconPath: '',
        label: {
          content: this.data.drawShape === 'rect' ? '角1' : '圆心',
          fontSize: 11, color: '#2563eb', bgColor: '#dbeafe',
          padding: 3, borderRadius: 8, anchorX: -10, anchorY: -24,
        },
      }
      this.setData({
        tapPoints: taps,
        polyMarkers: [marker],
        allMarkers: this.data.hazardMarkers.concat([marker]),
      })
    } else if (taps.length === 2) {
      this._buildShape(taps[0], taps[1])
      this.setData({ drawing: false, tapPoints: taps })
      wx.showToast({ title: '区域已选定', icon: 'success', duration: 1000 })
    }
  },

  _buildShape(p1, p2) {
    const points = this.data.drawShape === 'rect' ? this._buildRect(p1, p2) : this._buildCircle(p1, p2)
    this._applyPolygon(points)
  },

  _buildRect(p1, p2) {
    return [
      { latitude: p1.latitude, longitude: p1.longitude },
      { latitude: p1.latitude, longitude: p2.longitude },
      { latitude: p2.latitude, longitude: p2.longitude },
      { latitude: p2.latitude, longitude: p1.longitude },
    ]
  },

  _buildCircle(center, edge) {
    const dlat = edge.latitude - center.latitude
    const dlng = edge.longitude - center.longitude
    const radius = Math.sqrt(dlat * dlat + dlng * dlng)
    const points = []
    for (let i = 0; i < 36; i++) {
      const angle = (2 * Math.PI * i) / 36
      points.push({
        latitude: center.latitude + radius * Math.sin(angle),
        longitude: center.longitude + radius * Math.cos(angle),
      })
    }
    return points
  },

  _applyPolygon(points) {
    const sel = [{
      points: points,
      strokeColor: '#2563eb',
      strokeWidth: 3,
      fillColor: '#2563eb26',
    }]

    const polyMarkers = this.data.tapPoints.map((p, i) => ({
      id: 10000 + i, latitude: p.latitude, longitude: p.longitude,
      width: 20, height: 20, iconPath: '',
      label: {
        content: this.data.drawShape === 'rect' ? '角' + (i + 1) : (i === 0 ? '圆心' : '半径'),
        fontSize: 11, color: '#2563eb', bgColor: '#dbeafe',
        padding: 3, borderRadius: 8, anchorX: -10, anchorY: -24,
      },
    }))

    const selectedHazardCount = this.data.hazards.filter(
      h => h.lat && h.lng && util.pointInPolygon(h.lat, h.lng, points)
    ).length

    this.setData({
      polyPoints: points,
      polyMarkers,
      selectionPolygon: sel,
      allMarkers: this.data.hazardMarkers.concat(polyMarkers),
      selectedHazardCount,
    })
    this._mergePolygons()
  },

  resetPolygon() {
    this.setData({
      polyPoints: [], polyMarkers: [], selectionPolygon: [],
      tapPoints: [], allMarkers: this.data.hazardMarkers,
      drawing: false, selectedHazardCount: 0,
    })
    this._mergePolygons()
  },

  // ==================== 智能研判 ====================

  async startJudge() {
    if (this.data.judging) return
    this.setData({ judging: true })
    wx.showLoading({ title: '智能研判中...', mask: true })

    try {
      const w = this.data.weather || {}
      const payload = {
        weather: {
          rain_24h: parseFloat(w.rain24h) || 35,
          warning_level: util.parseWarningLevel(w.warning),
          forecast: w.forecast6h || '大雨',
        },
      }

      if (this.data.polyPoints.length >= 3) {
        const selectedHazards = this.data.hazards.filter(
          h => h.lat && h.lng && util.pointInPolygon(h.lat, h.lng, this.data.polyPoints)
        )
        if (selectedHazards.length > 0) payload.hazards = selectedHazards
        payload.center = util.polygonCenter(this.data.polyPoints)
      }

      const result = await api.judge.run(payload)
      const app = getApp()
      const riskInfo = result['1_综合风险等级'] || {}
      result._riskClass = util.riskClass(riskInfo['等级'])
      app.globalData.lastJudgeResult = result

      wx.hideLoading()
      this.setData({ judging: false })
      wx.navigateTo({ url: '/pages/result/result' })
    } catch (e) {
      wx.hideLoading()
      this.setData({ judging: false })
      util.showToast('研判失败，请检查网络')
      console.error('智能研判失败', e)
    }
  },
})
