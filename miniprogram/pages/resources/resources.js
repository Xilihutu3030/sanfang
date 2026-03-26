const api = require('../../utils/api')
const util = require('../../utils/util')
const config = require('../../utils/config')

Page({
  data: {
    tabs: config.RESOURCE_TAB_LIST,
    activeTab: 0,
    currentType: 'personnel',
    items: [],
    statistics: {},
    loading: false,
  },

  onShow() {
    this.loadResources()
  },

  switchTab(e) {
    const idx = e.currentTarget.dataset.idx
    this.setData({
      activeTab: idx,
      currentType: config.RESOURCE_TAB_LIST[idx].key,
    })
    this.loadResources()
  },

  async loadResources() {
    this.setData({ loading: true })
    try {
      const data = await api.resources.list(this.data.currentType)
      this.setData({
        items: data.items || [],
        statistics: data.statistics || {},
        loading: false,
      })
    } catch (e) {
      this.setData({ loading: false })
      console.error('加载资源失败', e)
    }
  },

  goAdd() {
    wx.navigateTo({
      url: `/pages/resource-add/resource-add?type=${this.data.currentType}`,
    })
  },

  goImport() {
    wx.navigateTo({
      url: `/pages/resource-import/resource-import?type=${this.data.currentType}`,
    })
  },

  goAiRecognize() {
    wx.navigateTo({
      url: `/pages/resource-ai/resource-ai?type=${this.data.currentType}`,
    })
  },

  async deleteItem(e) {
    const id = e.currentTarget.dataset.id
    const confirmed = await util.confirm('确认删除', '删除后不可恢复，确定删除？')
    if (!confirmed) return

    util.showLoading('删除中...')
    try {
      await api.resources.delete(this.data.currentType, id)
      util.hideLoading()
      util.showToast('已删除')
      this.loadResources()
    } catch (e) {
      util.hideLoading()
      util.showToast('删除失败')
    }
  },

  editItem(e) {
    const id = e.currentTarget.dataset.id
    wx.navigateTo({
      url: `/pages/resource-add/resource-add?type=${this.data.currentType}&id=${id}`,
    })
  },
})
