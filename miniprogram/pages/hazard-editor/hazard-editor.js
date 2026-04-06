const api = require('../../utils/api')

const levelClsMap = { '重大': 'major', '较大': 'moderate', '一般': 'minor' }

Page({
  data: {
    typeList: ['隧道', '地下空间', '河道', '危房', '边坡', '易涝点', '桥梁'],
    levelList: ['重大', '较大', '一般'],
    typeIdx: 0, levelIdx: 2,
    name: '', lat: '', lng: '', note: '',
    hazards: [],
  },

  onShow() { this.loadHazards() },

  onInput(e) { this.setData({ [e.currentTarget.dataset.f]: e.detail.value }) },
  onTypeChange(e) { this.setData({ typeIdx: +e.detail.value }) },
  onLevelChange(e) { this.setData({ levelIdx: +e.detail.value }) },

  pickLocation() {
    wx.chooseLocation({
      success: res => {
        this.setData({ lat: res.latitude.toFixed(4), lng: res.longitude.toFixed(4) })
        wx.showToast({ title: '已选取坐标', icon: 'success' })
      },
      fail: () => { wx.showToast({ title: '选点取消', icon: 'none' }) }
    })
  },

  async loadHazards() {
    try {
      const res = await api.customHazards.list()
      const hazards = (res.hazards || []).map(h => ({ ...h, levelCls: levelClsMap[h.level] || 'minor' }))
      this.setData({ hazards })
    } catch (e) {}
  },

  async saveHazard() {
    const { name, typeList, typeIdx, lat, lng, levelList, levelIdx, note } = this.data
    if (!name) { wx.showToast({ title: '请输入名称', icon: 'none' }); return }
    if (!lat || !lng) { wx.showToast({ title: '请输入坐标或从地图选点', icon: 'none' }); return }
    try {
      await api.customHazards.add({
        name, type: typeList[typeIdx],
        lat: +lat, lng: +lng,
        level: levelList[levelIdx], note,
      })
      wx.showToast({ title: '保存成功' })
      this.setData({ name: '', lat: '', lng: '', note: '' })
      this.loadHazards()
    } catch (e) { wx.showToast({ title: '保存失败', icon: 'none' }) }
  },

  async deleteHazard(e) {
    const id = e.currentTarget.dataset.id
    const res = await new Promise(r => wx.showModal({ title: '确认', content: '删除此风险点?', success: r }))
    if (!res.confirm) return
    try {
      await api.customHazards.delete(id)
      wx.showToast({ title: '已删除' })
      this.loadHazards()
    } catch (e) { wx.showToast({ title: '删除失败', icon: 'none' }) }
  },
})
