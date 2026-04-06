Component({
  data: {
    selected: 0,
    list: [
      {
        pagePath: "/pages/index/index",
        text: "首页",
        icon: "🏠",
        color: "#2196f3",
        gradientFrom: "#2196f3",
        gradientTo: "#64b5f6"
      },
      {
        pagePath: "/pages/resources/resources",
        text: "资源",
        icon: "📦",
        color: "#ff9800",
        gradientFrom: "#ff9800",
        gradientTo: "#ffb74d"
      },
      {
        pagePath: "/pages/history/history",
        text: "历史",
        icon: "📋",
        color: "#4caf50",
        gradientFrom: "#4caf50",
        gradientTo: "#81c784"
      },
      {
        pagePath: "/pages/profile/profile",
        text: "我的",
        icon: "👤",
        color: "#7c4dff",
        gradientFrom: "#7c4dff",
        gradientTo: "#b388ff"
      }
    ]
  },
  methods: {
    switchTab(e) {
      const data = e.currentTarget.dataset;
      const url = data.path;
      wx.switchTab({ url });
    }
  }
});
