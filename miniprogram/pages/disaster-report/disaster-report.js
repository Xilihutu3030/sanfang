const api = require('../../utils/api')

const typeList = ['flood', 'landslide', 'wind', 'road', 'rescue', 'other']
const typeLabels = ['积水内涝', '山体滑坡', '大风倒树', '道路损毁', '人员被困', '其他']
const sevList = ['low', 'medium', 'high', 'critical']
const sevLabels = ['轻微', '中等', '严重', '危急']

Page({
  data: {
    // 表单
    tab: 'submit', // submit | list
    typeIdx: 0,
    sevIdx: 1,
    typeLabels,
    sevLabels,
    title: '',
    description: '',
    location: '',
    lat: '',
    lng: '',
    mediaList: [], // [{url, type, localPath}]
    videoCount: 0,
    submitting: false,
    // 列表
    reports: [],
    stats: null,
    filterType: '',
  },

  onShow() {
    if (this.data.tab === 'list') this.loadReports()
  },

  onPullDownRefresh() {
    if (this.data.tab === 'list') {
      this.loadReports().then(() => wx.stopPullDownRefresh())
    } else {
      wx.stopPullDownRefresh()
    }
  },

  switchTab(e) {
    const tab = e.currentTarget.dataset.tab
    this.setData({ tab })
    if (tab === 'list') this.loadReports()
  },

  onInput(e) {
    this.setData({ [e.currentTarget.dataset.f]: e.detail.value })
  },

  onTypeChange(e) { this.setData({ typeIdx: +e.detail.value }) },
  onSevChange(e) { this.setData({ sevIdx: +e.detail.value }) },

  // 获取当前定位
  getLocation() {
    wx.getLocation({
      type: 'gcj02',
      success: res => {
        this.setData({
          lat: res.latitude.toFixed(6),
          lng: res.longitude.toFixed(6),
        })
        wx.showToast({ title: '定位成功', icon: 'success' })
      },
      fail: () => wx.showToast({ title: '定位失败，请检查权限', icon: 'none' })
    })
  },

  // 从地图选点
  pickLocation() {
    wx.chooseLocation({
      success: res => {
        this.setData({
          lat: res.latitude.toFixed(6),
          lng: res.longitude.toFixed(6),
          location: res.address || res.name || '',
        })
        wx.showToast({ title: '已选取位置', icon: 'success' })
      },
      fail: () => {}
    })
  },

  // 拍照/选择图片
  chooseImage() {
    const remain = 9 - this.data.mediaList.length
    if (remain <= 0) { wx.showToast({ title: '最多9张图片', icon: 'none' }); return }
    wx.chooseMedia({
      count: remain,
      mediaType: ['image'],
      sourceType: ['album', 'camera'],
      camera: 'back',
      success: res => {
        const newMedia = res.tempFiles.map(f => ({
          localPath: f.tempFilePath,
          type: 'image',
          url: '', // 上传后填入
          size: f.size,
        }))
        this.setData({ mediaList: [...this.data.mediaList, ...newMedia] })
        this._updateMediaStats()
      }
    })
  },

  // 拍视频
  chooseVideo() {
    if (this.data.mediaList.filter(m => m.type === 'video').length >= 1) {
      wx.showToast({ title: '最多1个视频', icon: 'none' }); return
    }
    wx.chooseMedia({
      count: 1,
      mediaType: ['video'],
      sourceType: ['album', 'camera'],
      maxDuration: 30,
      camera: 'back',
      success: res => {
        const f = res.tempFiles[0]
        const newMedia = [{
          localPath: f.tempFilePath,
          type: 'video',
          url: '',
          size: f.size,
          thumb: f.thumbTempFilePath || '',
        }]
        this.setData({ mediaList: [...this.data.mediaList, ...newMedia] })
        this._updateMediaStats()
      }
    })
  },

  // 删除媒体
  removeMedia(e) {
    const idx = e.currentTarget.dataset.idx
    const list = [...this.data.mediaList]
    list.splice(idx, 1)
    this.setData({ mediaList: list })
    this._updateMediaStats()
  },

  // 预览图片
  previewImage(e) {
    const idx = e.currentTarget.dataset.idx
    const urls = this.data.mediaList.filter(m => m.type === 'image').map(m => m.localPath || m.url)
    wx.previewImage({ urls, current: urls[idx] || urls[0] })
  },

  // 更新媒体统计（videoCount）
  _updateMediaStats() {
    const mediaList = this.data.mediaList
    this.setData({
      videoCount: mediaList.filter(m => m.type === 'video').length
    })
  },

  // 提交上报
  async submitReport() {
    const { title, typeIdx, sevIdx, description, location, lat, lng, mediaList } = this.data
    if (!title) { wx.showToast({ title: '请填写灾情标题', icon: 'none' }); return }
    if (!lat || !lng) { wx.showToast({ title: '请先定位或选择位置', icon: 'none' }); return }

    this.setData({ submitting: true })
    wx.showLoading({ title: '正在上报...' })

    try {
      // 1. 上传媒体文件
      const uploadedMedia = []
      for (let i = 0; i < mediaList.length; i++) {
        const m = mediaList[i]
        if (m.url) { uploadedMedia.push({ url: m.url, type: m.type }); continue }
        wx.showLoading({ title: `上传文件 ${i + 1}/${mediaList.length}...` })
        const result = await api.reports.upload(m.localPath)
        uploadedMedia.push({ url: result.url, type: result.type || m.type })
      }

      // 2. 创建上报
      const user = wx.getStorageSync('sf_user') || {}
      await api.reports.create({
        title,
        type: typeList[typeIdx],
        severity: sevList[sevIdx],
        description,
        location,
        lat: +lat,
        lng: +lng,
        media: uploadedMedia,
        user_id: user.id || '',
        user_name: user.display_name || user.username || '匿名市民',
      })

      wx.hideLoading()
      wx.showToast({ title: '上报成功!', icon: 'success' })

      // 重置表单
      this.setData({
        title: '', description: '', location: '',
        lat: '', lng: '', mediaList: [], videoCount: 0,
        typeIdx: 0, sevIdx: 1, submitting: false,
      })
    } catch (e) {
      wx.hideLoading()
      wx.showToast({ title: '上报失败: ' + (e.data?.error || '网络错误'), icon: 'none' })
      this.setData({ submitting: false })
    }
  },

  // 加载上报列表
  async loadReports() {
    try {
      const params = {}
      if (this.data.filterType) params.type = this.data.filterType
      params.hours = 48
      const res = await api.reports.list(params)
      this.setData({ reports: res.reports || [], stats: res.stats || null })
    } catch (e) {
      console.error('加载灾情上报失败', e)
    }
  },

  onFilterType(e) {
    const types = ['', ...typeList]
    this.setData({ filterType: types[e.detail.value] })
    this.loadReports()
  },

  // 点赞确认
  async upvoteReport(e) {
    const id = e.currentTarget.dataset.id
    try {
      const res = await api.reports.upvote(id)
      wx.showToast({ title: `已确认 (${res.upvotes}人)`, icon: 'success' })
      this.loadReports()
    } catch (e) {
      wx.showToast({ title: '操作失败', icon: 'none' })
    }
  },

  // 预览上报图片
  previewReportImage(e) {
    const { rptIdx, current } = e.currentTarget.dataset
    const report = this.data.reports[rptIdx]
    const urls = (report && report.media || []).filter(m => m.type === 'image').map(m => m.url)
    wx.previewImage({ urls: urls, current: current || urls[0] || '' })
  },
})
