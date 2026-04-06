const api = require('../../utils/api')

Page({
  data: { stations: [], loading: false },

  onShow() { this.loadStations() },

  async loadStations() {
    this.setData({ loading: true })
    try {
      const res = await api.water.stations()
      const stations = (res.stations || []).map(s => {
        const level = parseFloat(s.current_level) || 0
        const warn = parseFloat(s.warning_level) || 0
        const danger = parseFloat(s.danger_level) || 1
        let statusClass = 'normal', statusText = '正常'
        if (level >= danger) { statusClass = 'danger'; statusText = '超警戒' }
        else if (level >= warn) { statusClass = 'warning'; statusText = '接近警戒' }
        const percent = Math.min((level / danger) * 100, 100)
        return { ...s, current_level: level.toFixed(2), statusClass, statusText, percent: percent.toFixed(0) }
      })
      this.setData({ stations })
    } catch (e) { wx.showToast({ title: '加载失败', icon: 'none' }) }
    this.setData({ loading: false })
  },
})
