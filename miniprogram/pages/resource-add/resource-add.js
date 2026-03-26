const api = require('../../utils/api')
const util = require('../../utils/util')
const config = require('../../utils/config')

Page({
  data: {
    type: 'personnel',
    editId: '',
    title: '',
    fields: [],
    formData: {},
    pickerIndices: {},
    submitting: false,
    // 定位相关
    locating: false,
    locationLabel: '',  // 显示的位置文字
    // AI识别相关
    fromAi: false,
    aiFilledKeys: [],   // AI填写的字段key列表
  },

  onLoad(options) {
    const type = options.type || 'personnel'
    const editId = options.id || ''
    const formConfig = config.FORM_CONFIG[type]

    this.setData({
      type,
      editId,
      title: editId ? `编辑${formConfig.title}` : `添加${formConfig.title}`,
      fields: formConfig.fields,
    })

    wx.setNavigationBarTitle({ title: this.data.title })

    if (editId) {
      this.loadItem(type, editId)
    }

    // 消费AI识别预填数据
    const app = getApp()
    if (app.globalData.aiPrefillData) {
      this.applyAiResult(app.globalData.aiPrefillData)
      app.globalData.aiPrefillData = null
    }
  },

  async loadItem(type, id) {
    try {
      const data = await api.resources.list(type)
      const item = (data.items || []).find((i) => i.id === id)
      if (item) {
        const formData = {}
        this.data.fields.forEach((f) => {
          formData[f.key] = item[f.key] || ''
          if (Array.isArray(formData[f.key])) {
            formData[f.key] = formData[f.key].join(',')
          }
        })
        // 加载已保存的坐标
        if (item.lat && item.lng) {
          formData.lat = item.lat
          formData.lng = item.lng
          this.setData({
            locationLabel: `${item.lat.toFixed(5)}, ${item.lng.toFixed(5)}`,
          })
        }
        this.setData({ formData })
      }
    } catch (e) {
      console.error('加载数据失败', e)
    }
  },

  onInput(e) {
    const key = e.currentTarget.dataset.key
    this.setData({ [`formData.${key}`]: e.detail.value })
  },

  onPickerChange(e) {
    const key = e.currentTarget.dataset.key
    const field = this.data.fields.find((f) => f.key === key)
    const idx = parseInt(e.detail.value)
    this.setData({
      [`formData.${key}`]: field.picker[idx],
      [`pickerIndices.${key}`]: idx,
    })
  },

  // ==================== AI识别预填 ====================

  applyAiResult(result) {
    if (!result || !result.fields) return

    const formData = {}
    const aiFilledKeys = []
    const pickerIndices = {}

    this.data.fields.forEach((f) => {
      const val = result.fields[f.key]
      if (val !== undefined && val !== '') {
        formData[f.key] = String(val)
        aiFilledKeys.push(f.key)
        // 如果是 picker 类型，找到对应索引
        if (f.picker) {
          const idx = f.picker.indexOf(String(val))
          if (idx >= 0) {
            pickerIndices[f.key] = idx
          }
        }
      }
    })

    this.setData({
      formData,
      pickerIndices,
      fromAi: true,
      aiFilledKeys,
    })
  },

  // ==================== 定位功能 ====================

  // 自动获取当前 GPS 位置
  autoLocate() {
    this.setData({ locating: true })
    wx.getLocation({
      type: 'gcj02',
      success: (res) => {
        const lat = parseFloat(res.latitude.toFixed(6))
        const lng = parseFloat(res.longitude.toFixed(6))
        this._applyLocation(lat, lng, `当前位置 (${lat}, ${lng})`)
      },
      fail: (err) => {
        console.error('定位失败', err)
        wx.showToast({ title: '定位失败，请检查权限', icon: 'none' })
      },
      complete: () => {
        this.setData({ locating: false })
      },
    })
  },

  // 地图选点
  pickOnMap() {
    wx.chooseLocation({
      success: (res) => {
        const lat = parseFloat(res.latitude.toFixed(6))
        const lng = parseFloat(res.longitude.toFixed(6))
        const name = res.name || res.address || `${lat}, ${lng}`
        this._applyLocation(lat, lng, name)
        // 如果有 location/address 字段，顺带填入
        if (this.data.formData.location === '' || this.data.formData.address === '') {
          const addr = res.address || res.name || ''
          if ('location' in this.data.formData) {
            this.setData({ 'formData.location': addr })
          } else if ('address' in this.data.formData) {
            this.setData({ 'formData.address': addr })
          }
        }
      },
      fail: (err) => {
        if (err.errMsg && !err.errMsg.includes('cancel')) {
          wx.showToast({ title: '选点失败', icon: 'none' })
        }
      },
    })
  },

  // 清除位置
  clearLocation() {
    this.setData({
      'formData.lat': '',
      'formData.lng': '',
      locationLabel: '',
    })
  },

  _applyLocation(lat, lng, label) {
    this.setData({
      'formData.lat': lat,
      'formData.lng': lng,
      locationLabel: label,
    })
  },

  // ==================== 提交 ====================

  async submit() {
    if (this.data.submitting) return

    const { type, editId, formData, fields } = this.data

    for (const f of fields) {
      if (f.required && !formData[f.key]) {
        util.showToast(`请填写${f.label}`)
        return
      }
    }

    this.setData({ submitting: true })
    util.showLoading('提交中...')

    try {
      if (editId) {
        await api.resources.update(type, editId, formData)
      } else {
        await api.resources.add(type, formData)
      }
      util.hideLoading()
      util.showToast(editId ? '更新成功' : '添加成功')
      setTimeout(() => wx.navigateBack(), 800)
    } catch (e) {
      util.hideLoading()
      this.setData({ submitting: false })
      const msg = (e.data && e.data.error) || '操作失败'
      util.showToast(msg)
    }
  },
})
