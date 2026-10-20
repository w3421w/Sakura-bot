# 图片与表情素材

**本仓库不附带任何角色图片、GIF 或表情包文件。**

这里只保留：

- `manifest.json`：素材白名单模板（名称 → 文件路径 / QQ 表情 ID）
- `emotion_map.json`：情绪自动配图表

模型不能直接引用任意文件路径，只能使用 `manifest.json` 中登记的名称，例如：

```text
好的前辈 [sticker:shy]
```

## 添加自己的素材

1. 把你有权使用的 `.png`、`.jpg`、`.jpeg`、`.gif`、`.webp` 放进本目录或子目录；
2. 在 `manifest.json` 中登记：

```json
{
  "my_sakura_smile": {"type": "image", "file": "my_sakura_smile.png"}
}
```

3. 如需自动配图，把名称加入 `emotion_map.json` 的 `daily` / `black` 列表；
4. 重启 QWbot。

未登记的标记会被丢弃；`manifest.json` 中的 `face` 类型使用 OneBot11/NapCat 的 QQ 表情 ID。

## 版权

角色图片、同人图、GIF 和表情包的版权归原作者/权利方所有。仓库不提供这些文件，也不对你在本地添加的素材授予任何许可。请只使用你有权使用的素材，并自行确认再分发范围。
