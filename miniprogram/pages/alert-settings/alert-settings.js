const api = require('../../utils/api')

const COND_MAP = { rain_24h: '24h降雨', rain_1h: '1h降雨', warning_level: '预警等级', risk_score: '风险评分' }

Page({
  data: {
    conditionTypes: [
      { name: '24h降雨量', value: 'rain_24h' },
      { name: '1h降雨量', value: 'rain_1h' },
      { name: '预警等级', value: 'warning_level' },
      { name: '风险评分', value: 'risk_score' },
    ],
    notifyTypes: [
      { name: '页面提示', value: 'toast' },
      { name: '短信通知', value: 'sms' },
      { name: '微信通知', value: 'wechat' },
    ],
    condIdx: 0, notifyIdx: 0, threshold: '50',
    rules: [],
  },

  onShow() { this.loadRules() },

  onCondChange(e) { this.setData({ condIdx: +e.detail.value }) },
  onNotifyChange(e) { this.setData({ notifyIdx: +e.detail.value }) },
  onInput(e) { this.setData({ [e.currentTarget.dataset.f]: e.detail.value }) },

  async loadRules() {
    try {
      const res = await api.alerts.rules()
      const rules = (res.rules || []).map(r => ({
        ...r, condLabel: COND_MAP[r.condition_type] || r.condition_type,
      }))
      this.setData({ rules })
    } catch (e) { wx.showToast({ title: '加载失败', icon: 'none' }) }
  },

  async addRule() {
    const { conditionTypes, condIdx, threshold, notifyTypes, notifyIdx } = this.data
    if (!threshold) { wx.showToast({ title: '请输入阈值', icon: 'none' }); return }
    try {
      await api.alerts.addRule({
        condition_type: conditionTypes[condIdx].value,
        threshold: +threshold,
        notify_type: notifyTypes[notifyIdx].value,
      })
      wx.showToast({ title: '添加成功' })
      this.loadRules()
    } catch (e) { wx.showToast({ title: '添加失败', icon: 'none' }) }
  },

  async deleteRule(e) {
    const id = e.currentTarget.dataset.id
    const res = await new Promise(r => wx.showModal({ title: '确认', content: '删除此规则?', success: r }))
    if (!res.confirm) return
    try {
      await api.alerts.deleteRule(id)
      wx.showToast({ title: '已删除' })
      this.loadRules()
    } catch (e) { wx.showToast({ title: '删除失败', icon: 'none' }) }
  },
})
