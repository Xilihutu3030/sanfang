const api = require('../../utils/api')

Page({
  data: {
    tasks: [], stats: null, filter: '', loading: false,
    showAssign: false, assignTask: {}, assignStaffId: '', assignName: '', assignPhone: '', assignWechat: '', staffList: [],
    showDetail: false, detailTask: {}, detailLogs: [],
    lastAssignedTask: null, shareTask: null,
  },

  onShow() { this.loadTasks() },

  setFilter(e) {
    this.setData({ filter: e.currentTarget.dataset.v })
    this.loadTasks()
  },

  async loadTasks() {
    this.setData({ loading: true })
    try {
      const res = await api.tasks.list(this.data.filter)
      this.setData({ tasks: res.tasks || [], stats: res.stats || {} })
    } catch (e) { wx.showToast({ title: '加载失败', icon: 'none' }) }
    this.setData({ loading: false })
  },

  async generateTasks() {
    const app = getApp()
    const judge = app.globalData.lastJudgeResult
    if (!judge) { wx.showToast({ title: '请先执行智能研判', icon: 'none' }); return }
    wx.showLoading({ title: '生成中...' })
    try {
      const res = await api.tasks.batch({ judge_result: judge, hazards: app.globalData.hazardData || [] })
      wx.hideLoading()
      wx.showToast({ title: `已生成${(res.task_ids || []).length}个任务` })
      this.loadTasks()
    } catch (e) { wx.hideLoading(); wx.showToast({ title: '生成失败', icon: 'none' }) }
  },

  async batchAssign() {
    wx.showLoading({ title: '分配中...' })
    try {
      const [taskRes, staffRes] = await Promise.all([api.tasks.list('pending'), api.staff.onDuty()])
      const pending = taskRes.tasks || []
      const allStaff = staffRes.staff || []
      if (!pending.length) { wx.hideLoading(); wx.showToast({ title: '无待分配任务', icon: 'none' }); return }
      if (!allStaff.length) { wx.hideLoading(); wx.showToast({ title: '无在岗人员', icon: 'none' }); return }
      const leaders = allStaff.filter(s => /组长|队长|主任/.test(s.role || ''))
      const members = allStaff.filter(s => !/组长|队长|主任/.test(s.role || ''))
      const pool = members.length ? members : allStaff
      let li = 0, mi = 0, count = 0
      for (const t of pending) {
        let staff
        if (t.priority === 'urgent' && leaders.length) { staff = leaders[li % leaders.length]; li++ }
        else { staff = pool[mi % pool.length]; mi++ }
        try {
          await api.tasks.assign(t.id, { staff_id: staff.id, staff_name: staff.name, staff_phone: staff.phone || '' })
          count++
        } catch (e) {}
      }
      wx.hideLoading()
      wx.showToast({ title: `已分配${count}个任务` })
      this.loadTasks()
    } catch (e) { wx.hideLoading(); wx.showToast({ title: '批量分配失败', icon: 'none' }) }
  },

  async openAssign(e) {
    const task = this.data.tasks[e.currentTarget.dataset.idx]
    this.setData({ showAssign: true, assignTask: task, assignStaffId: '', assignName: '', assignPhone: '', assignWechat: '', lastAssignedTask: null })
    try {
      const res = await api.staff.onDuty()
      this.setData({ staffList: res.staff || [] })
    } catch (e) {}
  },

  pickStaff(e) {
    const s = this.data.staffList[e.currentTarget.dataset.idx]
    this.setData({ assignStaffId: s.id, assignName: s.name, assignPhone: s.phone || '' })
  },

  onAssignInput(e) { this.setData({ [e.currentTarget.dataset.f]: e.detail.value }) },
  closeAssign() { this.setData({ showAssign: false }) },

  async confirmAssign() {
    const { assignTask, assignStaffId, assignName, assignPhone, assignWechat } = this.data
    if (!assignName) { wx.showToast({ title: '请选择或输入负责人', icon: 'none' }); return }
    try {
      const res = await api.tasks.assign(assignTask.id, {
        staff_id: assignStaffId, staff_name: assignName,
        staff_phone: assignPhone, staff_wechat: assignWechat
      })
      wx.showToast({ title: '分配成功' })
      this.setData({
        lastAssignedTask: { ...assignTask, assigned_name: assignName, notify_text: res.notify_text || '' },
        shareTask: { ...assignTask, assigned_name: assignName, notify_text: res.notify_text || '' }
      })
      wx.showModal({
        title: '分配成功',
        content: '是否立即转发微信通知给负责人？',
        confirmText: '转发通知',
        cancelText: '稍后再说',
        success: (r) => {
          this.setData({ showAssign: false })
          this.loadTasks()
          if (r.confirm) {
            const text = this._buildNotifyText(assignTask, assignName)
            wx.setClipboardData({
              data: text,
              success: () => {
                wx.showToast({ title: '已复制，请粘贴发送', icon: 'none', duration: 3000 })
              }
            })
          }
        }
      })
    } catch (e) { wx.showToast({ title: '分配失败', icon: 'none' }) }
  },

  shareToWechat(e) {
    const task = this.data.tasks[e.currentTarget.dataset.idx]
    const text = this._buildNotifyText(task, task.assigned_name || task.staff_name || '')
    this.setData({ shareTask: task })
    wx.setClipboardData({
      data: text,
      success: () => {
        wx.showToast({ title: '已复制，请在微信中粘贴发送', icon: 'none', duration: 3000 })
      }
    })
  },

  _buildNotifyText(task, staffName) {
    const priMap = { urgent: '紧急', high: '重要', normal: '普通' }
    const pri = priMap[task.priority] || '普通'
    const now = new Date()
    const pad = n => String(n).padStart(2, '0')
    const timeStr = `${now.getFullYear()}-${pad(now.getMonth()+1)}-${pad(now.getDate())} ${pad(now.getHours())}:${pad(now.getMinutes())}`
    let text = '【三防任务通知】\n'
    text += '━━━━━━━━━━━━\n'
    text += `任务: ${task.title || ''}\n`
    text += `优先级: ${pri}\n`
    if (task.description) text += `内容: ${task.description}\n`
    if (task.location) text += `地点: ${task.location}\n`
    text += `负责人: ${staffName}\n`
    text += `指派时间: ${timeStr}\n`
    text += '━━━━━━━━━━━━\n'
    text += '请尽快查看并处理，完成后请回复反馈。'
    return text
  },

  onShareAppMessage() {
    const task = this.data.shareTask || this.data.lastAssignedTask
    if (task) {
      const priMap = { urgent: '紧急', high: '重要', normal: '普通' }
      return {
        title: `[${priMap[task.priority] || '普通'}] ${task.title || '三防任务通知'}`,
        path: '/pages/tasks/tasks'
      }
    }
    return { title: '三防指挥 - 任务调度', path: '/pages/tasks/tasks' }
  },

  async submitFeedback(e) {
    const id = e.currentTarget.dataset.id
    const res = await new Promise(resolve => {
      wx.showModal({
        title: '任务反馈', editable: true, placeholderText: '输入反馈内容',
        success: r => resolve(r)
      })
    })
    if (!res.confirm || !res.content) return
    const done = await new Promise(resolve => {
      wx.showModal({ title: '是否完成?', content: '该任务是否已完成?', success: r => resolve(r.confirm) })
    })
    try {
      await api.tasks.feedback(id, { status: done ? 'completed' : 'in_progress', feedback: res.content })
      wx.showToast({ title: '反馈成功' })
      this.loadTasks()
    } catch (e) { wx.showToast({ title: '提交失败', icon: 'none' }) }
  },

  async openDetail(e) {
    const id = e.currentTarget.dataset.id
    const task = this.data.tasks.find(t => t.id === id) || {}
    this.setData({ showDetail: true, detailTask: task, detailLogs: [] })
    try {
      const res = await api.tasks.logs(id)
      this.setData({ detailLogs: res.logs || [] })
    } catch (e) {}
  },

  closeDetail() { this.setData({ showDetail: false }) },
})
