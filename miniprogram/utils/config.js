/**
 * 三防系统 - 全局配置常量
 * 统一管理资源类型、表单配置等
 */

// ==================== 资源类型配置 ====================
const RESOURCE_TYPES = {
  personnel: {
    key: 'personnel',
    label: '人员队伍',
    icon: '👥',
  },
  materials: {
    key: 'materials',
    label: '物资装备',
    icon: '🔧',
  },
  facilities: {
    key: 'facilities',
    label: '场所设施',
    icon: '🏠',
  },
  vehicles: {
    key: 'vehicles',
    label: '车辆运力',
    icon: '🚗',
  },
}

// Tab 列表（用于页面展示）
const RESOURCE_TAB_LIST = Object.values(RESOURCE_TYPES)

// 类型标签映射
const RESOURCE_TYPE_LABELS = Object.fromEntries(
  Object.entries(RESOURCE_TYPES).map(([k, v]) => [k, v.label])
)

// ==================== 表单字段配置 ====================
const FORM_CONFIG = {
  personnel: {
    title: '人员队伍',
    fields: [
      { key: 'name', label: '姓名', required: true, placeholder: '请输入姓名' },
      { key: 'type', label: '类型', picker: ['救援队员', '巡查人员', '值班人员', '志愿者', '其他'] },
      { key: 'team', label: '队伍', placeholder: '如: 区应急救援队' },
      { key: 'phone', label: '联系电话', required: true, type: 'number', placeholder: '请输入手机号' },
      { key: 'skills', label: '技能(逗号分隔)', placeholder: '如: 水上救援,医疗急救' },
      { key: 'status', label: '状态', picker: ['待命', '在岗', '休假', '外派'] },
      { key: 'location', label: '所在位置', placeholder: '如: XX消防站' },
    ],
  },
  materials: {
    title: '物资装备',
    fields: [
      { key: 'name', label: '物资名称', required: true, placeholder: '如: 移动水泵' },
      { key: 'category', label: '类别', picker: ['排水设备', '照明设备', '防护用品', '救生器材', '通信设备', '其他'] },
      { key: 'quantity', label: '数量', required: true, type: 'number', placeholder: '请输入数量' },
      { key: 'unit', label: '单位', placeholder: '如: 台/套/个' },
      { key: 'location', label: '存放位置', placeholder: '如: XX仓库' },
      { key: 'status', label: '状态', picker: ['可用', '使用中', '维修中', '报废'] },
      { key: 'specs', label: '规格说明', placeholder: '如: 功率200kW' },
      { key: 'manager', label: '管理员', placeholder: '请输入管理员姓名' },
      { key: 'manager_phone', label: '联系电话', type: 'number', placeholder: '管理员手机号' },
    ],
  },
  facilities: {
    title: '场所设施',
    fields: [
      { key: 'name', label: '设施名称', required: true, placeholder: '如: XX应急避难所' },
      { key: 'type', label: '类型', picker: ['避难所', '仓库', '指挥中心', '医疗点', '物资点', '其他'] },
      { key: 'capacity', label: '容纳人数', type: 'number', placeholder: '请输入容量' },
      { key: 'address', label: '详细地址', required: true, placeholder: '请输入地址' },
      { key: 'contact', label: '负责人', placeholder: '请输入负责人姓名' },
      { key: 'phone', label: '联系电话', type: 'number', placeholder: '请输入手机号' },
      { key: 'status', label: '状态', picker: ['备用', '使用中', '维护中', '关闭'] },
    ],
  },
  vehicles: {
    title: '车辆运力',
    fields: [
      { key: 'plate_number', label: '车牌号', required: true, placeholder: '如: 粤A12345' },
      { key: 'type', label: '车辆类型', required: true, picker: ['抢险车', '运输车', '指挥车', '救护车', '消防车', '其他'] },
      { key: 'model', label: '车辆型号', placeholder: '如: 东风应急车' },
      { key: 'driver', label: '驾驶员', placeholder: '请输入驾驶员姓名' },
      { key: 'driver_phone', label: '联系电话', type: 'number', placeholder: '请输入手机号' },
      { key: 'status', label: '状态', picker: ['可用', '出勤中', '维修中', '报废'] },
      { key: 'location', label: '存放位置', placeholder: '如: XX停车场' },
    ],
  },
}

// ==================== 预警等级配置 ====================
const WARNING_LEVELS = {
  红色: { level: 4, color: '#dc2626', class: 'warning-red' },
  橙色: { level: 3, color: '#ea580c', class: 'warning-orange' },
  黄色: { level: 2, color: '#d97706', class: 'warning-yellow' },
  蓝色: { level: 1, color: '#2563eb', class: 'warning-blue' },
}

// ==================== 风险等级配置 ====================
const RISK_LEVELS = {
  极高: { class: 'risk-extreme', color: '#dc2626' },
  高: { class: 'risk-high', color: '#ea580c' },
  中: { class: 'risk-mid', color: '#d97706' },
  低: { class: 'risk-low', color: '#2563eb' },
}

module.exports = {
  RESOURCE_TYPES,
  RESOURCE_TAB_LIST,
  RESOURCE_TYPE_LABELS,
  FORM_CONFIG,
  WARNING_LEVELS,
  RISK_LEVELS,
}
