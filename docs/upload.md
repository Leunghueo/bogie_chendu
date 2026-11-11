# 数据上传功能开发

## 接口描述

### 接口信息

格式: `Content-Type 为 application/json; charset=UTF-8`

地址: `http://10.194.96.177:8000/api/v3/equipmentData`

### 数据格式
以下为`静载实验台样数据样例`, 备注表明了数据来源.
```
{
  "OnlineToken":  # 搜索路径: app.ini->push->config文件->isdp->token
  "DeviceCode": # 搜索路径: app.ini->bed->bed.json->设备编号,
  "DataType": "DEVICEDATA",
  "CheckData": {
    "任务编号": {
      "BYXLL1": # 结果数据->空簧保压泄漏量1,
      "BYXLL2": # 结果数据->空簧保压泄漏量2,
      "CYFXLL1": # 结果数据->差压1泄漏量,
      "CYFXLL2": # 结果数据->差压2泄漏量,
      "CYFXLL2": # 结果数据->空簧保压泄漏量2,
      "ZJCC1": # 结果数据->轴距13,
      "ZJCC2": # 结果数据->轴距24,
      "ZXJGJX1": # 结果数据->1位轴箱与构架间距,
      "ZXJGJX2": # 结果数据->2位轴箱与构架间距,
      "ZXJGJX3": # 结果数据->3位轴箱与构架间距,
      "ZXJGJX4": # 结果数据->4位轴箱与构架间距,
      "LZJGDC1": # 结果数据->联轴节高度差1,
      "LZJGDC2": # 结果数据->联轴节高度差2,
    }
  },
  "BasicInfo": {
    "DeviceName": # 搜索路径: app.ini->bed->bed.json->设备名称,,
    "CheckTime": # 试验结束时间,
    "TrnsetType": # 车型,
    "TrnsetNo": # 车号,
    "TrnsetTrainNo": # 架位号,
    "PositionNo": # 架位号,
    "SerialNum": "",
    "OperatorName": # user,
    "OperatorID": "",
    "Remark": ""
  }
}
```

以下为应答示例:
```
{
  "resCode": "0",                       // 应答码，0 表示接口调用成功
  "resMsg": "成功",                     // 对接口调用结果的详细说明
  "devCode": "dev-10001",               // 设备编码，唯一标识返回内容所属的设备
  "reqId": "REQUEST-20260915-0001",     // 请求编码，用于请求的全链路追踪
  "timestamp": "1757894400"             // 时间戳，记录响应生成的时间
}
```
## 代码位置
创建`libs\push\isdp.py`文件并在其中编写核心代码

## UI
在`历史页面`的`上传EMIS`旁边添加按钮`上传ISDP`, 根据应答提示上传结果.
