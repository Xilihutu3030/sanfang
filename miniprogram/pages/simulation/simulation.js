const api = require('../../utils/api')

Page({
  data: {
    rain24: '100', rain1: '30', forecast: '中到大雨',
    warningIdx: 2,
    warningLevels: [
      { name: '无预警', value: 0 },
      { name: '蓝色预警', value: 1 },
      { name: '黄色预警', value: 2 },
      { name: '橙色预警', value: 3 },
      { name: '红色预警', value: 4 },
    ],
    loading: false, multiLoading: false,
    singleResult: null, riskClass: '',
    multiResults: [],
  },

  onInput(e) {
    this.setData({ [e.currentTarget.dataset.field]: e.detail.value })
  },

  onWarningChange(e) {
    this.setData({ warningIdx: +e.detail.value })
  },

  async runSingle() {
    this.setData({ loading: true, singleResult: null })
    try {
      const { rain24, rain1, forecast, warningLevels, warningIdx } = this.data
      const payload = {
        rain_24h: +rain24, rain_1h: +rain1,
        warning_level: warningLevels[warningIdx].value,
        forecast: forecast,
      }
      const app = getApp()
      if (app.globalData.drawnShape) payload.area = app.globalData.drawnShape
      if (app.globalData.hazardData) payload.hazards = app.globalData.hazardData

      const res = await api.simulate.run(payload)
      const riskClass = (res.risk_level || '').includes('高') ? 'risk-high' :
                        (res.risk_level || '').includes('中') ? 'risk-mid' : 'risk-low'
      this.setData({ singleResult: res, riskClass })
    } catch (e) {
      wx.showToast({ title: '推演失败', icon: 'none' })
    }
    this.setData({ loading: false })
  },

  async runMulti() {
    this.setData({ multiLoading: true, multiResults: [] })
    const scenarios = [
      { label: '蓝色预警', rain_24h: 50, rain_1h: 15, warning_level: 1, forecast: '中雨', color: '#2196f3' },
      { label: '黄色预警', rain_24h: 100, rain_1h: 30, warning_level: 2, forecast: '大雨', color: '#ffc107' },
      { label: '橙色预警', rain_24h: 150, rain_1h: 50, warning_level: 3, forecast: '暴雨', color: '#ff9800' },
      { label: '红色预警', rain_24h: 250, rain_1h: 80, warning_level: 4, forecast: '大暴雨', color: '#f44336' },
    ]
    try {
      const res = await api.simulate.run({ scenarios })
      const results = (res.results || scenarios).map((r, i) => ({
        ...scenarios[i], ...r,
        score: r.score || r.risk_score || 0,
      }))
      this.setData({ multiResults: results })
    } catch (e) {
      wx.showToast({ title: '多场景推演失败', icon: 'none' })
    }
    this.setData({ multiLoading: false })
  },
})
