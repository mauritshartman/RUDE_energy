import{c as y,e as d,a as h,d as w,h as z,u as $,j as f,m as T,n as c,bs as R,J as a}from"./index-TvjCra5P.js";const B=y("h",`
 font-size: var(--n-font-size);
 font-weight: var(--n-font-weight);
 margin: var(--n-margin);
 transition: color .3s var(--n-bezier);
 color: var(--n-text-color);
`,[d("&:first-child",{marginTop:0}),h("prefix-bar",{position:"relative",paddingLeft:"var(--n-prefix-width)"},[h("align-text",{paddingLeft:0},[d("&::before",{left:"calc(-1 * var(--n-prefix-width))"})]),d("&::before",`
 content: "";
 width: var(--n-bar-width);
 border-radius: calc(var(--n-bar-width) / 2);
 transition: background-color .3s var(--n-bezier);
 left: 0;
 top: 0;
 bottom: 0;
 position: absolute;
 `),d("&::before",{backgroundColor:"var(--n-bar-color)"})])]),P=Object.assign(Object.assign({},f.props),{type:{type:String,default:"default"},prefix:String,alignText:Boolean}),W=r=>w({name:`H${r}`,props:P,setup(e){const{mergedClsPrefixRef:i,inlineThemeDisabled:o}=$(e),n=f("Typography","-h",B,R,e,i),s=c(()=>{const{type:l}=e,{common:{cubicBezierEaseInOut:g},self:{headerFontWeight:b,headerTextColor:m,[a("headerPrefixWidth",r)]:p,[a("headerFontSize",r)]:u,[a("headerMargin",r)]:x,[a("headerBarWidth",r)]:C,[a("headerBarColor",l)]:v}}=n.value;return{"--n-bezier":g,"--n-font-size":u,"--n-margin":x,"--n-bar-color":v,"--n-bar-width":C,"--n-font-weight":b,"--n-text-color":m,"--n-prefix-width":p}}),t=o?T(`h${r}`,c(()=>e.type[0]),s,e):void 0;return{mergedClsPrefix:i,cssVars:o?void 0:s,themeClass:t?.themeClass,onRender:t?.onRender}},render(){var e;const{prefix:i,alignText:o,mergedClsPrefix:n,cssVars:s,$slots:t}=this;return(e=this.onRender)===null||e===void 0||e.call(this),z(`h${r}`,{class:[`${n}-h`,`${n}-h${r}`,this.themeClass,{[`${n}-h--prefix-bar`]:i,[`${n}-h--align-text`]:o}],style:s},t)}}),S=W("4");export{S as N};
