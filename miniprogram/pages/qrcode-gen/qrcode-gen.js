const app = getApp()

Page({
  data: {
    region: '',
    org: '',
    fullUrl: '',
    generated: false,
    saving: false,
    canvasWidth: 400,
    canvasHeight: 540,
    posterMode: 'server',  // server: 服务端生成海报, local: 本地Canvas绘制
  },

  onInput(e) {
    this.setData({ [e.currentTarget.dataset.f]: e.detail.value })
  },

  generateQR() {
    const { region, org } = this.data
    if (!region) {
      wx.showToast({ title: '请输入区域名称', icon: 'none' })
      return
    }

    // 构建上报URL
    const base = app.globalData.apiBase || ''
    const params = `?r=${encodeURIComponent(region)}&ch=qrcode` + (org ? `&org=${encodeURIComponent(org)}` : '')
    const fullUrl = base + '/report' + params

    this.setData({ fullUrl, generated: false })

    wx.showLoading({ title: '生成中...' })

    // 优先使用服务端海报API
    this._tryServerPoster(fullUrl, region, org)
  },

  // 方案1: 服务端生成完整海报（含真实二维码）
  _tryServerPoster(url, region, org) {
    const base = app.globalData.apiBase || ''
    const posterUrl = `${base}/api/qrcode/poster?region=${encodeURIComponent(region)}` +
      (org ? `&org=${encodeURIComponent(org)}` : '')

    // 先下载服务端生成的海报
    wx.downloadFile({
      url: posterUrl,
      success: (res) => {
        if (res.statusCode === 200 && res.tempFilePath) {
          // 将海报绘制到Canvas上
          this._drawServerPoster(res.tempFilePath)
        } else {
          console.warn('服务端海报生成失败，使用本地二维码方案')
          this._tryServerQR(url, region, org)
        }
      },
      fail: () => {
        console.warn('服务端海报下载失败，使用本地二维码方案')
        this._tryServerQR(url, region, org)
      }
    })
  },

  // 方案2: 获取服务端二维码图片，本地绘制海报
  _tryServerQR(url, region, org) {
    const base = app.globalData.apiBase || ''
    const qrUrl = `${base}/api/qrcode?url=${encodeURIComponent(url)}&size=440`

    wx.downloadFile({
      url: qrUrl,
      success: (res) => {
        if (res.statusCode === 200 && res.tempFilePath) {
          this._drawLocalPosterWithQR(res.tempFilePath, region, org)
        } else {
          // 最终兜底：纯本地绘制（无真实二维码）
          this._drawLocalPosterPlaceholder(url, region, org)
        }
      },
      fail: () => {
        this._drawLocalPosterPlaceholder(url, region, org)
      }
    })
  },

  // 将服务端海报直接画到Canvas
  _drawServerPoster(imgPath) {
    const ctx = wx.createCanvasContext('qr-canvas', this)
    const W = this.data.canvasWidth
    const H = this.data.canvasHeight

    ctx.drawImage(imgPath, 0, 0, W, H)
    ctx.draw(false, () => {
      wx.hideLoading()
      this.setData({ generated: true, posterMode: 'server' })
      wx.showToast({ title: '海报已生成', icon: 'success' })
    })
  },

  // 本地绘制海报 + 服务端二维码图片
  _drawLocalPosterWithQR(qrImgPath, region, org) {
    const ctx = wx.createCanvasContext('qr-canvas', this)
    const W = this.data.canvasWidth
    const H = this.data.canvasHeight

    // 白色背景
    ctx.setFillStyle('#ffffff')
    ctx.fillRect(0, 0, W, H)

    // 顶部蓝色条
    const grd = ctx.createLinearGradient(0, 0, W, 80)
    grd.addColorStop(0, '#0277bd')
    grd.addColorStop(1, '#00bcd4')
    ctx.setFillStyle(grd)
    ctx.fillRect(0, 0, W, 80)

    // 标题
    ctx.setFillStyle('#ffffff')
    ctx.setFontSize(22)
    ctx.setTextAlign('center')
    ctx.fillText(region + ' 灾情上报', W / 2, 36)

    ctx.setFontSize(13)
    ctx.setGlobalAlpha(0.85)
    ctx.fillText('扫码上报灾情 · 助力应急指挥', W / 2, 60)
    ctx.setGlobalAlpha(1)

    // 二维码图片
    const qrSize = 220
    const qrX = (W - qrSize) / 2
    const qrY = 100

    // 边框
    ctx.setStrokeStyle('#e0e0e0')
    ctx.setLineWidth(2)
    ctx.strokeRect(qrX - 10, qrY - 10, qrSize + 20, qrSize + 20)

    // 绘制真实二维码
    ctx.drawImage(qrImgPath, qrX, qrY, qrSize, qrSize)

    // 底部说明
    this._drawPosterBottom(ctx, W, H, qrY + qrSize + 30, org)

    ctx.draw(false, () => {
      wx.hideLoading()
      this.setData({ generated: true, posterMode: 'local' })
      wx.showToast({ title: '海报已生成', icon: 'success' })
    })
  },

  // 本地绘制 - 无真实二维码（兜底）
  _drawLocalPosterPlaceholder(url, region, org) {
    const ctx = wx.createCanvasContext('qr-canvas', this)
    const W = this.data.canvasWidth
    const H = this.data.canvasHeight

    ctx.setFillStyle('#ffffff')
    ctx.fillRect(0, 0, W, H)

    const grd = ctx.createLinearGradient(0, 0, W, 80)
    grd.addColorStop(0, '#0277bd')
    grd.addColorStop(1, '#00bcd4')
    ctx.setFillStyle(grd)
    ctx.fillRect(0, 0, W, 80)

    ctx.setFillStyle('#ffffff')
    ctx.setFontSize(22)
    ctx.setTextAlign('center')
    ctx.fillText(region + ' 灾情上报', W / 2, 36)

    ctx.setFontSize(13)
    ctx.setGlobalAlpha(0.85)
    ctx.fillText('扫码上报灾情 · 助力应急指挥', W / 2, 60)
    ctx.setGlobalAlpha(1)

    const qrSize = 220
    const qrX = (W - qrSize) / 2
    const qrY = 100

    ctx.setStrokeStyle('#e0e0e0')
    ctx.setLineWidth(2)
    ctx.strokeRect(qrX - 10, qrY - 10, qrSize + 20, qrSize + 20)

    // 占位文本
    ctx.setFillStyle('#263238')
    ctx.setFontSize(14)
    ctx.fillText('[ 二维码 ]', W / 2, qrY + qrSize / 2 - 10)
    ctx.setFillStyle('#78909c')
    ctx.setFontSize(11)
    ctx.fillText('请通过"复制链接"分享', W / 2, qrY + qrSize / 2 + 10)

    this._drawPosterBottom(ctx, W, H, qrY + qrSize + 30, org)

    ctx.draw(false, () => {
      wx.hideLoading()
      this.setData({ generated: true, posterMode: 'placeholder' })
      wx.showToast({ title: '链接已生成（二维码需联网）', icon: 'none' })
    })
  },

  // 公共底部绘制
  _drawPosterBottom(ctx, W, H, bottomY, org) {
    ctx.setFillStyle('#263238')
    ctx.setFontSize(15)
    ctx.setTextAlign('center')
    ctx.fillText('微信扫一扫 · 快速上报灾情', W / 2, bottomY)

    ctx.setFillStyle('#78909c')
    ctx.setFontSize(12)
    ctx.fillText('拍照/视频 + 自动定位 + 实时上报', W / 2, bottomY + 22)

    if (org) {
      ctx.setFillStyle('#0277bd')
      ctx.setFontSize(13)
      ctx.fillText(org, W / 2, bottomY + 48)
    }

    ctx.setFillStyle('#b0bec5')
    ctx.setFontSize(10)
    ctx.fillText('紧急险情请拨打 119 / 110', W / 2, H - 15)
  },

  // 保存海报到相册
  savePoster() {
    this.setData({ saving: true })
    wx.canvasToTempFilePath({
      canvasId: 'qr-canvas',
      quality: 1,
      success: res => {
        wx.saveImageToPhotosAlbum({
          filePath: res.tempFilePath,
          success: () => {
            wx.showToast({ title: '已保存到相册', icon: 'success' })
          },
          fail: () => {
            wx.showToast({ title: '保存失败，请检查相册权限', icon: 'none' })
          },
          complete: () => this.setData({ saving: false })
        })
      },
      fail: () => {
        wx.showToast({ title: '生成图片失败', icon: 'none' })
        this.setData({ saving: false })
      }
    }, this)
  },

  // 复制链接
  copyLink() {
    wx.setClipboardData({
      data: this.data.fullUrl,
      success: () => wx.showToast({ title: '链接已复制', icon: 'success' })
    })
  },

  // 预览海报
  previewPoster() {
    wx.canvasToTempFilePath({
      canvasId: 'qr-canvas',
      quality: 1,
      success: res => {
        wx.previewImage({ urls: [res.tempFilePath] })
      }
    }, this)
  },
})
