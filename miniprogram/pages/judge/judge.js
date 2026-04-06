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
    // 行政区域选择
    provinceList: [],
    cityList: [],
    districtList: [],
    townList: [],
    provinceIdx: -1,
    cityIdx: -1,
    districtIdx: -1,
    townIdx: -1,
    regionPath: '',
    regionSelected: {},  // {province, city, district, town}
    regionBbox: null,
    regionCenter: null,
    regionBorderPolygons: [],
    showRegionBorder: false,
    _isMunicipality: false,
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
    this.loadProvinces()
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
      // 获取当前区域名称和中心坐标
      const rs = this.data.regionSelected || {}
      const regionName = (rs.district && rs.district.name) || (rs.city && rs.city.name !== '直辖市' && rs.city.name) || (rs.province && rs.province.name) || ''
      const center = this.data.regionCenter ? { latitude: this.data.regionCenter.lat, longitude: this.data.regionCenter.lng } : this.data.mapCenter
      const bbox = this.data.regionBbox || null
      const data = await api.hazards.list(regionName, center.latitude, center.longitude, bbox)
      let hazards = data.hazards || []

      // 前端硬性过滤：有区域边界时，只保留bbox范围内的点（安全兜底）
      if (bbox && regionName) {
        hazards = hazards.filter(function(h) {
          return h.lat && h.lng &&
            h.lat >= bbox.sw_lat && h.lat <= bbox.ne_lat &&
            h.lng >= bbox.sw_lng && h.lng <= bbox.ne_lng
        })
      }

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
            content: h.name + (h.ai_risk_score ? '(' + h.ai_risk_score + ')' : ''),
            fontSize: 10,
            color: h.level === '重大' ? '#dc2626' : (h.level === '较大' ? '#d97706' : '#3b82f6'),
            bgColor: '#ffffff',
            padding: 3,
            borderRadius: 4,
          },
          callout: {
            content: h.name + '\n' + h.type + ' | ' + h.level
              + '\n高程: ' + (h.elevation || '--') + 'm'
              + (h.description ? '\n' + h.description : ''),
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

  async aiAnalyzeHazards() {
    const rs = this.data.regionSelected || {}
    const regionName = (rs.district && rs.district.name) || (rs.city && rs.city.name !== '直辖市' && rs.city.name) || (rs.province && rs.province.name) || ''
    if (!regionName) {
      wx.showToast({ title: '请先选择区域', icon: 'none' })
      return
    }
    wx.showLoading({ title: 'AI分析中...' })
    try {
      const center = this.data.regionCenter ? { latitude: this.data.regionCenter.lat, longitude: this.data.regionCenter.lng } : this.data.mapCenter
      // 根据区域bbox计算合理半径
      let radiusKm = 15
      const bbox = this.data.regionBbox
      if (bbox) {
        const dlat = bbox.ne_lat - bbox.sw_lat
        const dlng = bbox.ne_lng - bbox.sw_lng
        radiusKm = Math.max(dlat, dlng) * 111 / 2
        radiusKm = Math.max(5, Math.min(radiusKm, 50))
      }
      const data = await api.hazards.aiAnalyze({
        region: regionName,
        center_lat: center.latitude,
        center_lng: center.longitude,
        radius_km: radiusKm,
      })
      let hazards = data.hazards || []

      // 前端硬性过滤：有区域边界时，只保留bbox范围内的点
      if (bbox) {
        hazards = hazards.filter(function(h) {
          return h.lat && h.lng &&
            h.lat >= bbox.sw_lat && h.lat <= bbox.ne_lat &&
            h.lng >= bbox.sw_lng && h.lng <= bbox.ne_lng
        })
      }

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
            content: h.name + (h.ai_risk_score ? '(' + h.ai_risk_score + ')' : ''),
            fontSize: 10,
            color: h.level === '重大' ? '#dc2626' : (h.level === '较大' ? '#d97706' : '#3b82f6'),
            bgColor: '#ffffff',
            padding: 3,
            borderRadius: 4,
          },
          callout: {
            content: h.name + '\n' + h.type + ' | ' + h.level
              + (h.description ? '\n' + h.description : ''),
            fontSize: 12,
            color: '#1e293b',
            bgColor: '#ffffff',
            padding: 8,
            borderRadius: 8,
            display: 'BYCLICK',
          },
        }))
      this.setData({ hazards, hazardMarkers, allMarkers: hazardMarkers })
      this._buildRiverFromHazards(hazards)
      const tag = data.ai_enhanced ? 'AI增强' : '知识库'
      wx.showToast({ title: tag + '：' + hazards.length + '个风险点', icon: 'none' })
    } catch (e) {
      console.error('AI风险分析失败', e)
      wx.showToast({ title: 'AI分析失败', icon: 'none' })
    } finally {
      wx.hideLoading()
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
      .concat(this.data.showRegionBorder ? this.data.regionBorderPolygons : [])
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
    // 手动圈选 → 清除行政区域选择
    if (this.data.regionPath) {
      this.clearRegion()
    }
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

      // 优先使用行政区域，其次手动圈选
      const rs = this.data.regionSelected
      if (this.data.regionBbox && rs.province) {
        const bb = this.data.regionBbox
        payload.area = { type: 'rectangle', swLat: bb.sw_lat, swLng: bb.sw_lng, neLat: bb.ne_lat, neLng: bb.ne_lng }
        if (this.data.regionCenter) {
          payload.center = { lat: this.data.regionCenter.lat, lng: this.data.regionCenter.lng }
        }
        var parts = []
        ;['province', 'city', 'district', 'town'].forEach(function(k) {
          if (rs[k] && rs[k].name !== '直辖市') parts.push(rs[k].name)
        })
        payload.region_name = parts.join('')
        // 传递当前已加载的风险点数据
        if (this.data.hazards && this.data.hazards.length > 0) {
          payload.hazards = this.data.hazards
        }
      } else if (this.data.polyPoints.length >= 3) {
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
      app.globalData.sessionJudgeHistory.push(result)

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

  // ==================== 行政区域选择 ====================

  async loadProvinces() {
    try {
      const data = await api.regions.provinces()
      this.setData({ provinceList: data.regions || [] })
    } catch (e) {
      console.error('省份加载失败', e)
    }
  },

  async onProvinceChange(e) {
    const idx = parseInt(e.detail.value)
    const prov = this.data.provinceList[idx]
    if (!prov) return
    // 清除手动圈选
    this._clearDrawIfNeeded()
    this.setData({
      provinceIdx: idx,
      cityList: [], cityIdx: -1,
      districtList: [], districtIdx: -1,
      townList: [], townIdx: -1,
      regionSelected: { province: prov },
      _isMunicipality: false,
    })
    this._updateRegionPath()
    // 加载子级 → _loadChildren 会自动处理直辖市
    this._loadChildren(prov.code, 'cityList')
    this._loadRegionBoundary(prov.code)
  },

  async onCityChange(e) {
    const idx = parseInt(e.detail.value)
    const city = this.data.cityList[idx]
    if (!city) return
    this._clearDrawIfNeeded()
    const rs = this.data.regionSelected
    rs.city = city
    rs.district = null
    rs.town = null
    this.setData({
      cityIdx: idx,
      districtList: [], districtIdx: -1,
      townList: [], townIdx: -1,
      regionSelected: rs,
    })
    this._updateRegionPath()
    this._loadChildren(city.code, 'districtList')
    this._loadRegionBoundary(city.code)
  },

  async onDistrictChange(e) {
    const idx = parseInt(e.detail.value)
    const dist = this.data.districtList[idx]
    if (!dist) return
    this._clearDrawIfNeeded()
    const rs = this.data.regionSelected
    rs.district = dist
    rs.town = null
    this.setData({
      districtIdx: idx,
      townList: [], townIdx: -1,
      regionSelected: rs,
    })
    this._updateRegionPath()
    this._loadChildren(dist.code, 'townList')
    this._loadRegionBoundary(dist.code)
  },

  async onTownChange(e) {
    const idx = parseInt(e.detail.value)
    const town = this.data.townList[idx]
    if (!town) return
    this._clearDrawIfNeeded()
    const rs = this.data.regionSelected
    rs.town = town
    this.setData({ townIdx: idx, regionSelected: rs })
    this._updateRegionPath()
    // 乡镇定位：调用地理编码精确定位
    const cityName = (rs.city && rs.city.name !== '直辖市') ? rs.city.name : (rs.province ? rs.province.name : '')
    const query = town.name + ' ' + cityName
    try {
      const geo = await api.regions.geocode(query)
      if (geo && geo.lat && geo.lng) {
        const bb = geo.bbox
        const bbox = bb || {
          sw_lat: geo.lat - 0.015, sw_lng: geo.lng - 0.015,
          ne_lat: geo.lat + 0.015, ne_lng: geo.lng + 0.015,
        }
        // 用bbox画矩形边界
        const rectPoints = [
          { latitude: bbox.sw_lat, longitude: bbox.sw_lng },
          { latitude: bbox.sw_lat, longitude: bbox.ne_lng },
          { latitude: bbox.ne_lat, longitude: bbox.ne_lng },
          { latitude: bbox.ne_lat, longitude: bbox.sw_lng },
        ]
        const polys = [{
          points: rectPoints,
          strokeColor: '#e65100',
          strokeWidth: 2,
          fillColor: '#ff98000f',
          dashArray: [12, 8],
        }]
        this.setData({
          regionCenter: { lat: geo.lat, lng: geo.lng },
          regionBbox: bbox,
          regionBorderPolygons: polys,
          showRegionBorder: true,
          mapCenter: { latitude: geo.lat, longitude: geo.lng },
        })
        this._mergePolygons()
        this.loadDEM()
        return
      }
    } catch (err) {
      console.warn('乡镇地理编码失败，回退到区县中心', err)
    }
    // 回退：用父级区县中心
    const pc = this.data._parentCenter
    if (pc) {
      this.setData({
        regionCenter: { lat: pc.lat, lng: pc.lng },
        mapCenter: { latitude: pc.lat, longitude: pc.lng },
      })
      this.loadDEM()
    }
  },

  async _loadChildren(code, listKey) {
    try {
      const data = await api.regions.children(code)
      const regions = data.regions || []
      const update = {}
      // 保存父级中心坐标（乡镇定位用）
      if (data.parent_center) {
        update._parentCenter = { lng: data.parent_center[0], lat: data.parent_center[1] }
      }
      // 直辖市特殊处理：后端已跳过"市辖区"，区县直接填到districtList
      if (data.is_municipality && listKey === 'cityList') {
        update.cityList = [{ code: 'municipality', name: '直辖市' }]
        update.cityIdx = 0
        update.districtList = regions
        update.districtIdx = -1
        update.townList = []
        update.townIdx = -1
        update._isMunicipality = true
        const rs = this.data.regionSelected
        rs.city = { code: 'municipality', name: '直辖市' }
        update.regionSelected = rs
      } else {
        update[listKey] = regions
      }
      this.setData(update)
    } catch (e) {
      console.warn('加载子区域失败', e)
    }
  },

  async _loadRegionBoundary(code) {
    try {
      const data = await api.regions.boundary(code, false, true)
      if (!data || !data.features) return
      const polys = []
      let allLats = [], allLngs = []
      let center = null

      data.features.forEach(feat => {
        const geom = feat.geometry
        if (!geom) return
        const props = feat.properties || {}
        const c = props.center || props.centroid
        if (c) center = { lat: c[1], lng: c[0] }

        const rings = []
        if (geom.type === 'Polygon') {
          rings.push(...geom.coordinates)
        } else if (geom.type === 'MultiPolygon') {
          geom.coordinates.forEach(p => rings.push(...p))
        }

        rings.forEach(ring => {
          const points = ring.map(c => {
            allLngs.push(c[0])
            allLats.push(c[1])
            return { latitude: c[1], longitude: c[0] }
          })
          polys.push({
            points: points,
            strokeColor: '#0277bd',
            strokeWidth: 3,
            fillColor: '#0288d10d',
            dashArray: [10, 5],
          })
        })
      })

      const bbox = allLats.length > 0 ? {
        sw_lat: Math.min(...allLats), sw_lng: Math.min(...allLngs),
        ne_lat: Math.max(...allLats), ne_lng: Math.max(...allLngs),
      } : null

      // 兜底：如果GeoJSON没有center属性，从bbox中心计算
      if (!center && bbox) {
        center = {
          lat: (bbox.sw_lat + bbox.ne_lat) / 2,
          lng: (bbox.sw_lng + bbox.ne_lng) / 2,
        }
      }

      this.setData({
        regionBorderPolygons: polys,
        regionBbox: bbox,
        regionCenter: center,
        showRegionBorder: true,
      })
      this._mergePolygons()

      // 自动移动地图中心到区域中心，并重新加载风险点和地形
      if (center) {
        this.setData({
          mapCenter: { latitude: center.lat, longitude: center.lng },
        })
      }
      this.loadHazards()
      this.loadDEM()
    } catch (e) {
      console.warn('边界加载失败', e)
    }
  },

  _updateRegionPath() {
    const rs = this.data.regionSelected
    const parts = []
    ;['province', 'city', 'district', 'town'].forEach(k => {
      if (rs[k] && rs[k].name !== '直辖市') parts.push(rs[k].name)
    })
    this.setData({ regionPath: parts.join(' > ') })
  },

  flyToRegion() {
    const bb = this.data.regionBbox
    if (!bb) {
      wx.showToast({ title: '请先选择区域', icon: 'none' })
      return
    }
    // 清除手动圈选
    this._clearDrawIfNeeded()
    const cLat = (bb.sw_lat + bb.ne_lat) / 2
    const cLng = (bb.sw_lng + bb.ne_lng) / 2
    this.setData({
      mapCenter: { latitude: cLat, longitude: cLng },
      showRegionBorder: true,
    })
    this._mergePolygons()
    // 刷新DEM
    this.loadDEM()
  },

  toggleRegionBorder() {
    if (!this.data.regionBorderPolygons.length) {
      wx.showToast({ title: '请先选择区域', icon: 'none' })
      return
    }
    this.setData({ showRegionBorder: !this.data.showRegionBorder })
    this._mergePolygons()
  },

  clearRegion() {
    this.setData({
      provinceIdx: -1, cityIdx: -1, districtIdx: -1, townIdx: -1,
      cityList: [], districtList: [], townList: [],
      regionPath: '',
      regionSelected: {},
      regionBbox: null,
      regionCenter: null,
      regionBorderPolygons: [],
      showRegionBorder: false,
      _isMunicipality: false,
    })
    this._mergePolygons()
  },

  _clearDrawIfNeeded() {
    if (this.data.polyPoints.length > 0 || this.data.drawing) {
      this.setData({
        polyPoints: [], polyMarkers: [], selectionPolygon: [],
        tapPoints: [], allMarkers: this.data.hazardMarkers,
        drawing: false, selectedHazardCount: 0,
      })
      this._mergePolygons()
    }
  },
})
