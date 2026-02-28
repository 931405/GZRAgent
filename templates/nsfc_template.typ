// nsfc_template.typ
// 国自然基金/通用学术文档 Typst 模板

#let conf(
  title: "国家自然科学基金申请书",
  project_type: "面上项目",
  date_str: "2026 年",
  doc,
) = {
  // 设置页面大小和页边距
  set page(
    paper: "a4",
    margin: (x: 2.5cm, y: 3cm),
    header: align(right)[
      #text(8pt, fill: luma(100))[#project_type]
    ],
    numbering: "1",
  )
  
  // 字体设置
  // 中文使用宋体，英文使用 Times New Roman
  set text(
    font: ("Times New Roman", "SimSun"),
    size: 12pt,
    lang: "zh",
  )

  // 段落设置设置首行缩进
  set par(
    first-line-indent: 2em,
    justify: true,
    leading: 1.2em,
  )

  // 标题样式
  show heading: it => {
    set text(font: ("Times New Roman", "SimHei"), weight: "bold", fill: rgb("#1F497D"))
    if it.level == 1 {
      v(1.5em)
      text(16pt, it.body)
      v(1em)
    } else if it.level == 2 {
      v(1.2em)
      text(14pt, it.body)
      v(0.8em)
    } else {
      v(1em)
      text(13pt, it.body)
      v(0.6em)
    }
  }

  // 封面
  align(center)[
    #v(3cm)
    #text(22pt, weight: "bold", font: ("Times New Roman", "SimHei"), fill: rgb("#1F497D"))[国家自然科学基金]
    
    #v(1cm)
    #text(20pt, weight: "bold", font: ("Times New Roman", "SimHei"))[申 请 书]
    
    #v(4cm)
    #grid(
      columns: 2,
      row-gutter: 1.5em,
      column-gutter: 1em,
      align(right)[#text(14pt, weight: "bold")[项目类型：]], align(left)[#text(14pt, project_type)],
      align(right)[#text(14pt, weight: "bold")[研究主题：]], align(left)[#text(14pt, title)],
    )

    #v(4cm)
    #text(12pt)[#date_str]
  ]

  pagebreak()

  // 正文
  doc
}
