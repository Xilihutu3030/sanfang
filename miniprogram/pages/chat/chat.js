const api = require('../../utils/api')
const util = require('../../utils/util')

Page({
  data: {
    messages: [],
    inputText: '',
    sessionId: '',
    context: null,
    loading: false,
    quickQuestions: [
      '哪个点位最需要优先处置？',
      '需要调派多少抢险人员？',
      '群众转移方案怎么安排？',
      '当前预警还会持续多久？',
    ],
  },

  onLoad(options) {
    const app = getApp()
    const result = app.globalData.lastJudgeResult
    if (result) {
      // 提取摘要作为对话上下文
      const context = {
        '风险等级': result['1_综合风险等级'],
        '主要风险': result['2_主要风险类型'],
        'Top5点位': result['3_Top5危险点位'],
        '淹没预判': result['4_淹没预判'],
        '指挥建议': result['5_指挥建议'],
      }
      this.setData({ context })
    }

    // 添加欢迎消息
    this.addMessage('assistant', '您好，我是三防AI助手。已获取最新研判结果，您可以就研判内容向我提问，例如具体点位处置方案、人员调配建议等。')
  },

  onUnload() {
    // 页面卸载时无需特殊处理，会话保留在后端
  },

  // 发送消息
  async sendMessage() {
    const text = this.data.inputText.trim()
    if (!text || this.data.loading) return

    this.addMessage('user', text)
    this.setData({ inputText: '', loading: true })

    try {
      const res = await api.chat.send(text, this.data.context, this.data.sessionId)
      this.setData({ sessionId: res.session_id || this.data.sessionId })
      this.addMessage('assistant', res.reply || '抱歉，未获取到回复。')
    } catch (e) {
      console.error('chat error', e)
      const errMsg = (e && e.data && e.data.error) || 'AI助手暂时无法响应，请稍后再试。'
      this.addMessage('assistant', errMsg)
    } finally {
      this.setData({ loading: false })
    }
  },

  // 快捷问题
  tapQuick(e) {
    const q = e.currentTarget.dataset.q
    this.setData({ inputText: q })
    this.sendMessage()
  },

  // 输入绑定
  onInput(e) {
    this.setData({ inputText: e.detail.value })
  },

  // 添加消息到列表
  addMessage(role, content) {
    const messages = this.data.messages.concat({
      id: util.generateId(),
      role: role,
      content: content,
      time: util.formatTimeShort(),
    })
    this.setData({ messages }, () => {
      this._scrollToBottom()
    })
  },

  // 滚动到底部
  _scrollToBottom() {
    const len = this.data.messages.length
    if (len > 0) {
      this.setData({ scrollInto: 'msg-' + this.data.messages[len - 1].id })
    }
  },

  // 长按复制消息
  copyMessage(e) {
    const content = e.currentTarget.dataset.content
    util.copyText(content)
  },
})
