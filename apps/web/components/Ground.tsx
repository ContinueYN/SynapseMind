/**
 * 底：白 → 浅蓝的一池琉璃。
 *
 * 三团光只做极慢的呼吸（90/120/150s），不跟随指针、不做视差——
 * 背景一旦会追人，注意力就被拉走了。玻璃面板自己会接光，这就够了。
 */
export function Ground() {
  return (
    <div aria-hidden="true" className="sm-bg">
      <span className="sm-blob sm-blob-1" />
      <span className="sm-blob sm-blob-2" />
      <span className="sm-blob sm-blob-3" />
    </div>
  );
}