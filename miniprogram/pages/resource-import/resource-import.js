const api = require('../../utils/api')
const util = require('../../utils/util')
const config = require('../../utils/config')

Page({
  data: {
    type: 'personnel',
    typeLabel: '',
    importing: false,
    result: null,
  },

  onLoad(options) {
    const type = options.type || 'personnel'
    this.setData({
      type,
      typeLabel: config.RESOURCE_TYPE_LABELS[type] || type,
    })
    wx.setNavigationBarTitle({ title: `导入${this.data.typeLabel}` })
  },

  chooseFile() {
    wx.chooseMessageFile({
      count: 1,
      type: 'file',
      extension: ['xlsx', 'xls', 'csv'],
      success: (res) => {
        const file = res.tempFiles[0]
        this.uploadFile(file.path, file.name)
      },
      fail: () => {
        util.showToast('未选择文件')
      },
    })
  },

  async uploadFile(filePath, fileName) {
    this.setData({ importing: true, result: null })
    wx.showLoading({ title: '导入中...', mask: true })

    try {
      const result = await api.resources.import(this.data.type, filePath)
      wx.hideLoading()
      this.setData({
        importing: false,
        result: {
          ...result,
          fileName,
        },
      })

      if (result.imported > 0) {
        util.showToast(`成功导入 ${result.imported} 条`)
      } else {
        util.showToast('导入失败，请检查文件格式')
      }
    } catch (e) {
      wx.hideLoading()
      this.setData({ importing: false })
      util.showToast('导入失败')
      console.error('导入错误', e)
    }
  },

  downloadTemplate() {
    const url = api.resources.templateUrl(this.data.type)
    wx.downloadFile({
      url,
      success: (res) => {
        if (res.statusCode === 200) {
          wx.openDocument({
            filePath: res.tempFilePath,
            showMenu: true,
            success: () => {},
            fail: () => {
              util.showToast('请用其他方式打开文件')
            },
          })
        }
      },
      fail: () => {
        util.showToast('下载模板失败')
      },
    })
  },

  goBack() {
    wx.navigateBack()
  },
})
