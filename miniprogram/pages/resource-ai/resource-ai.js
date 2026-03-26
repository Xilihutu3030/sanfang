const api = require('../../utils/api')
const util = require('../../utils/util')
const config = require('../../utils/config')

Page({
  data: {
    type: 'personnel',
    typeLabel: '',
    step: 'select',       // select | preview | recognizing | result | error
    filePath: '',
    fileType: 'image',    // image | document
    fileName: '',
    result: null,         // { fields: {}, confidence: {} }
    fieldList: [],        // 用于展示的 [{label, key, value, confidence}]
    errorMsg: '',
  },

  onLoad(options) {
    const type = options.type || 'personnel'
    this.setData({
      type,
      typeLabel: config.RESOURCE_TYPE_LABELS[type] || type,
    })
  },

  // ==================== 文件选择 ====================

  chooseCamera() {
    wx.chooseMedia({
      count: 1,
      mediaType: ['image'],
      sourceType: ['camera'],
      success: (res) => {
        this._setFile(res.tempFiles[0].tempFilePath, 'image', '拍照图片')
      },
      fail: () => {},
    })
  },

  chooseAlbum() {
    wx.chooseMedia({
      count: 1,
      mediaType: ['image'],
      sourceType: ['album'],
      success: (res) => {
        this._setFile(res.tempFiles[0].tempFilePath, 'image', '相册图片')
      },
      fail: () => {},
    })
  },

  chooseDocument() {
    wx.chooseMessageFile({
      count: 1,
      type: 'file',
      extension: ['pdf', 'doc', 'docx', 'jpg', 'jpeg', 'png'],
      success: (res) => {
        const file = res.tempFiles[0]
        const ext = file.name.split('.').pop().toLowerCase()
        const isImage = ['jpg', 'jpeg', 'png'].includes(ext)
        this._setFile(file.path, isImage ? 'image' : 'document', file.name)
      },
      fail: () => {},
    })
  },

  _setFile(filePath, fileType, fileName) {
    this.setData({
      filePath,
      fileType,
      fileName,
      step: 'preview',
      result: null,
      fieldList: [],
      errorMsg: '',
    })
  },

  // ==================== 重选 / 重试 ====================

  reselect() {
    this.setData({
      step: 'select',
      filePath: '',
      fileName: '',
      result: null,
      fieldList: [],
      errorMsg: '',
    })
  },

  retry() {
    this.startRecognize()
  },

  // ==================== AI识别 ====================

  async startRecognize() {
    this.setData({ step: 'recognizing', errorMsg: '' })

    try {
      const result = await api.resources.recognize(
        this.data.type,
        this.data.filePath,
        this.data.fileType
      )

      if (!result || !result.fields) {
        this.setData({
          step: 'error',
          errorMsg: '识别结果为空，请确保文档内容清晰',
        })
        return
      }

      // 将 fields 转为列表用于展示
      const formFields = config.FORM_CONFIG[this.data.type].fields
      const fieldList = formFields
        .filter(f => result.fields[f.key])
        .map(f => ({
          label: f.label,
          key: f.key,
          value: result.fields[f.key],
          confidence: result.confidence ? result.confidence[f.key] : null,
        }))

      this.setData({
        step: 'result',
        result,
        fieldList,
      })
    } catch (e) {
      console.error('AI识别失败', e)
      const msg = (e.data && e.data.error) || '识别失败，请检查网络或重试'
      this.setData({ step: 'error', errorMsg: msg })
    }
  },

  // ==================== 填入表单 ====================

  goFillForm() {
    const app = getApp()
    app.globalData.aiPrefillData = this.data.result

    wx.redirectTo({
      url: `/pages/resource-add/resource-add?type=${this.data.type}&from=ai`,
    })
  },
})
