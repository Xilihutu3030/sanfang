const api = require('../../utils/api')

Page({
  data: {
    cameras: [],
    filteredCameras: [],
    cities: [],
    types: [
      { value: '', label: '全部类型' },
      { value: 'scenic', label: '景区' },
      { value: 'water', label: '水利' },
      { value: 'traffic', label: '交通' },
      { value: 'flood', label: '内涝' },
      { value: 'public', label: '社会公益' },
    ],
    typeLabels: { traffic: '交通', water: '水利', flood: '内涝', scenic: '景区', public: '社会公益', other: '其他' },
    selectedCity: '',
    selectedType: '',
    cityIndex: 0,
    typeIndex: 0,
    loading: false,
    playingCam: null,
    showAdd: false,
    // 添加表单
    form: { name: '', city: '', type: 'traffic', protocol: 'hls', lat: '', lng: '', stream_url: '', source: '' },
  },

  onShow() { this.loadCameras() },

  async loadCameras() {
    this.setData({ loading: true })
    try {
      const res = await api.cameras.list({
        city: this.data.selectedCity,
        type: this.data.selectedType,
      })
      const cameras = (res.cameras || []).map(c => ({
        ...c,
        typeLabel: this.data.typeLabels[c.type] || '其他',
        statusColor: c.status === 'online' ? '#10b981' : '#94a3b8',
        statusText: c.status === 'online' ? '在线' : '离线',
      }))
      // 提取城市列表
      const citySet = {}
      cameras.forEach(c => { if (c.city) citySet[c.city] = 1 })
      const cities = [{ value: '', label: '全部城市' }]
      Object.keys(citySet).sort().forEach(c => cities.push({ value: c, label: c }))

      this.setData({ cameras, filteredCameras: cameras, cities })
    } catch (e) {
      wx.showToast({ title: '加载失败', icon: 'none' })
    }
    this.setData({ loading: false })
  },

  onCityChange(e) {
    const idx = e.detail.value
    const city = this.data.cities[idx] ? this.data.cities[idx].value : ''
    this.setData({ cityIndex: idx, selectedCity: city })
    this.loadCameras()
  },

  onTypeChange(e) {
    const idx = e.detail.value
    const type = this.data.types[idx] ? this.data.types[idx].value : ''
    this.setData({ typeIndex: idx, selectedType: type })
    this.loadCameras()
  },

  playCam(e) {
    const cam = e.currentTarget.dataset.cam
    this.setData({ playingCam: cam })
  },

  stopPlay() {
    this.setData({ playingCam: null })
  },

  locateCam(e) {
    const cam = e.currentTarget.dataset.cam
    wx.openLocation({
      latitude: cam.lat,
      longitude: cam.lng,
      name: cam.name,
      address: (cam.city || '') + ' ' + (cam.source || ''),
      scale: 15,
    })
  },

  toggleAdd() {
    this.setData({ showAdd: !this.data.showAdd })
  },

  onFormInput(e) {
    const field = e.currentTarget.dataset.field
    this.setData({ [`form.${field}`]: e.detail.value })
  },

  onFormTypePick(e) {
    const types = ['scenic', 'water', 'traffic', 'flood', 'public']
    this.setData({ 'form.type': types[e.detail.value] || 'scenic' })
  },

  onFormProtocolPick(e) {
    const protocols = ['hls', 'mp4', 'flv']
    this.setData({ 'form.protocol': protocols[e.detail.value] || 'hls' })
  },

  chooseLocation() {
    wx.chooseLocation({
      success: (res) => {
        this.setData({
          'form.lat': res.latitude.toFixed(4),
          'form.lng': res.longitude.toFixed(4),
        })
      }
    })
  },

  async saveCamera() {
    const f = this.data.form
    if (!f.name || !f.lat || !f.lng || !f.stream_url) {
      wx.showToast({ title: '请填写必填项', icon: 'none' })
      return
    }
    try {
      await api.cameras.add({
        name: f.name,
        city: f.city,
        type: f.type,
        protocol: f.protocol,
        lat: parseFloat(f.lat),
        lng: parseFloat(f.lng),
        stream_url: f.stream_url,
        source: f.source,
      })
      wx.showToast({ title: '添加成功', icon: 'success' })
      this.setData({
        showAdd: false,
        form: { name: '', city: '', type: 'traffic', protocol: 'hls', lat: '', lng: '', stream_url: '', source: '' },
      })
      this.loadCameras()
    } catch (e) {
      wx.showToast({ title: '添加失败', icon: 'none' })
    }
  },

  async deleteCam(e) {
    const cam = e.currentTarget.dataset.cam
    const res = await wx.showModal({ title: '确认删除', content: `确定删除"${cam.name}"？` })
    if (!res.confirm) return
    try {
      await api.cameras.delete(cam.id)
      wx.showToast({ title: '已删除', icon: 'success' })
      this.loadCameras()
    } catch (e) {
      wx.showToast({ title: '删除失败', icon: 'none' })
    }
  },

  videoError(e) {
    console.log('Video error:', e.detail)
  },
})
