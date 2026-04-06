const api = require('../../utils/api')
const util = require('../../utils/util')

Page({
  data: {
    result: null,
    riskClass: 'risk-low',
    riskInfo: {},
    mainRisks: [],
    top5: [],
    flood: {},
    suggestions: [],
    leaderReport: '',
    sessionCount: 0,
    responseReport: '',
    showResponseReport: false,
    generatingReport: false,
  },

  onLoad() {
    const app = getApp()
    const result = app.globalData.lastJudgeResult
    if (!result) {
      util.showToast('无研判数据')
      wx.navigateBack()
      return
    }

    const riskInfo = result['1_综合风险等级'] || {}
    this.setData({
      result,
      riskClass: util.riskClass(riskInfo['等级']),
      riskInfo,
      mainRisks: result['2_主要风险类型'] || [],
      top5: result['3_Top5危险点位'] || [],
      flood: result['4_淹没预判'] || {},
      suggestions: result['5_指挥建议'] || [],
      leaderReport: result['6_领导汇报'] || '',
      sessionCount: app.globalData.sessionJudgeHistory.length,
    })
  },

  onShareAppMessage() {
    const level = this.data.riskInfo['等级'] || '研判结果'
    return {
      title: `【三防研判】${level} - ${util.formatTime(new Date())}`,
      path: '/pages/index/index',
    }
  },

  copyReport() {
    const text = this.data.result['简报文本'] || this.data.leaderReport
    if (text) {
      util.copyText(text)
    } else {
      util.showToast('暂无简报')
    }
  },

  copyLeaderReport() {
    if (this.data.leaderReport) {
      util.copyText(this.data.leaderReport)
    }
  },

  async saveHistory() {
    util.showLoading('保存中...')
    try {
      await api.history.save(this.data.result)
      util.hideLoading()
      util.showToast('已保存')
    } catch (e) {
      util.hideLoading()
      util.showToast('保存失败')
    }
  },

  async generateResponseReport() {
    const app = getApp()
    const records = app.globalData.sessionJudgeHistory
    if (!records || records.length === 0) {
      util.showToast('本次会话尚未进行研判')
      return
    }

    this.setData({ generatingReport: true })
    wx.showLoading({ title: '生成报告中...', mask: true })

    try {
      const regionName = this.data.result['研判区域'] || ''
      const data = await api.judge.responseReport({
        records: records,
        region_name: regionName,
      })

      wx.hideLoading()
      if (data.error) {
        this.setData({ generatingReport: false })
        util.showToast('生成失败: ' + data.error)
        return
      }

      this.setData({
        responseReport: data.report,
        showResponseReport: true,
        generatingReport: false,
      })
    } catch (e) {
      wx.hideLoading()
      this.setData({ generatingReport: false })
      util.showToast('生成报告失败')
      console.error('生成应急响应报告失败', e)
    }
  },

  copyResponseReport() {
    if (this.data.responseReport) {
      util.copyText(this.data.responseReport)
    } else {
      util.showToast('暂无报告内容')
    }
  },

  closeResponseReport() {
    this.setData({ showResponseReport: false })
  },

  confirmEndResponse() {
    const app = getApp()
    wx.showModal({
      title: '确认结束响应',
      content: '结束后将清空本次会话的研判记录，是否确认？',
      success: (res) => {
        if (res.confirm) {
          app.globalData.sessionJudgeHistory = []
          this.setData({
            showResponseReport: false,
            sessionCount: 0,
          })
          util.showToast('响应已结束')
          wx.navigateBack()
        }
      },
    })
  },

  shareResult() {
    // 触发微信分享
  },

  goChat() {
    wx.navigateTo({ url: '/pages/chat/chat' })
  },
})
