/**
 * 底：白 → 浅蓝的一池琉璃，分成好几层，各自一个景深。
 *
 * 滚页面的时候，这几层往上走的量不同（`--scroll` 由 ScrollRule 写进来）：
 * 近处的水光走得快，远处的游光几乎不动——页面因此有"厚度"。
 * 光斑不跟随指针：背景一旦会追人，注意力就被拉走了。
 *
 * 层次（从远到近）：游光 → 呼吸光斑 → 蓝光带 → 底缘光池 → 颗粒。
 */
export function Ground() {
  return (
    <div aria-hidden="true" className="sm-bg">
      <span className="sm-bg-veil" />
      <span className="sm-blob sm-blob-1" />
      <span className="sm-blob sm-blob-2" />
      <span className="sm-blob sm-blob-3" />
      <span className="sm-bg-floor" />
      <span className="sm-bg-grain" />
    </div>
  );
}