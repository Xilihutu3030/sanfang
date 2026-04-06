const api = require('../../utils/api')

Page({
  data: { records: [], loading: false, searched: false },

  async searchSimilar() {
    this.setData({ loading: true, searched: false })
    try {
      const weather = await api.weather.get()
      const rain24 = parseFloat(weather.rain_24h) || 0
      const rain1 = parseFloat(weather.rain_1h) || 0
      const res = await api.history.compare(rain24, rain1)
      const records = (res.records || []).map(r => ({
        ...r,
        timeShort: (r.time || '').substring(0, 16),
        similarity: r.similarity || 0,
      }))
      this.setData({ records, searched: true })
    } catch (e) { wx.showToast({ title: '搜索失败', icon: 'none' }) }
    this.setData({ loading: false })
  },
})
