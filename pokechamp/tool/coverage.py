"""Weighted 1v1 coverage of the team vs META, and partner search over POOL for the core."""
import math, itertools
from calc import *
from meta import META
from team import TEAM

def best(att, dfn, **kw):
    out=None
    for mv in att.moves:
        if MOVE[mv]['cat']=='status': continue
        a=att
        if att.species=='ギルガルド':
            a=Mon('ブレードギルガルド',att.nature,att.spv,'バトルスイッチ',att.item,att.moves)
        r=calc(a,dfn,mv,def_full_hp=False,**kw)
        pct=(r[0]/dfn.stat['hp']*100, r[-1]/dfn.stat['hp']*100)
        if out is None or pct[1]>out[1][1]: out=(mv,pct)
    return out

def verdict(me, foe):
    m1,p1=best(me,foe)
    burn = 'おにび' in me.moves and 'fire' not in foe.types and foe.ability not in ('ねつこうかん','こんじょう')
    m2,p2=best(foe,me,intimidated=me.ability=='いかく')
    if burn:
        mb,pb=best(foe,me,intimidated=me.ability=='いかく',burned=True)
        if MOVE[m2]['cat']=='physical': m2,p2=mb,pb
    fast=me.speed()>foe.speed(); tie=me.speed()==foe.speed()
    my_n=math.ceil(100/p1[0]) if p1[0]>0 else 99
    th_n=math.ceil(100/p2[1]) if p2[1]>0 else 99
    if burn and my_n>1: my_n+=1  # spend a turn on WoW
    if me.item=='きあいのタスキ' and th_n==1: th_n=2
    if foe.item=='きあいのタスキ' and my_n==1: my_n=2
    if foe.ability=='ばけのかわ': my_n+=1
    if me.ability=='ばけのかわ': th_n+=1
    if tie and my_n==th_n: return 0.5
    win=my_n<th_n or (my_n==th_n and fast)
    return (1.0 if th_n>=3 else 0.8) if win else 0

W={1:10,2:9,3:9,4:8,5:8,6:7,7:7,8:6,9:6,10:6,11:5,12:5,13:5,14:4,15:4,16:4,17:4,18:4,19:3,20:3,21:3,23:3,24:3,25:2,27:2,28:2,31:2,36:2,39:2,54:2}

POOL=[
 Mon('ミミッキュ','いじっぱり',dict(hp=1,atk=32,defn=1,spe=32),'ばけのかわ','いのちのたま',['じゃれつく','かげうち','つるぎのまい','シャドークロー']),
 Mon('サーフゴー','ひかえめ',dict(hp=2,spa=32,spe=32),'おうごんのからだ','ふうせん',['シャドーボール','ゴールドラッシュ','わるだくみ','じこさいせい']),
 Mon('セグレイブ','いじっぱり',dict(hp=1,atk=32,spe=32),'ねつこうかん','きあいのタスキ',['こおりのつぶて','じしん','きょけんとつげき','つららおとし']),
 Mon('ウォッシュロトム','ずぶとい',dict(hp=32,defn=32,spd=2),'ふゆう','たべのこし',['ハイドロポンプ','ボルトチェンジ','おにび','いたみわけ']),
 Mon('ギャラドス','わんぱく',{'hp':32,'def':32,'atk':2},'いかく','ゴツゴツメット',['たきのぼり','じしん','ちょうはつ','りゅうのまい']),
 Mon('アーマーガア','わんぱく',{'hp':32,'def':32,'spd':2},'ミラーアーマー','ゴツゴツメット',['はねやすめ','とんぼがえり','ボディプレス','てっぺき']),
 Mon('カバルドン','わんぱく',{'hp':32,'spd':32,'def':2},'すなおこし','オボンのみ',['じしん','あくび','ステルスロック','ふきとばし']),
 Mon('マスカーニャ','ようき',dict(hp=2,atk=32,spe=32),'へんげんじざい','こだわりスカーフ',['トリックフラワー','トリプルアクセル','はたきおとす','とんぼがえり']),
 Mon('イダイトウ','ようき',dict(hp=2,atk=32,spe=32),'てきおうりょく','こだわりスカーフ',['おはかまいり','ウェーブタックル','アクアジェット','クイックターン']),
 Mon('ドドゲザン','いじっぱり',dict(hp=32,atk=32,spe=2),'そうだいしょう','くろいメガネ',['ふいうち','ドゲザン','アイアンヘッド','つるぎのまい']),
 Mon('ゴリランダー','いじっぱり',dict(hp=32,atk=32,spe=2),'グラスメイカー','いのちのたま',['グラススライダー','とんぼがえり','はたきおとす','10まんばりき']),
 Mon('カイリュー','いじっぱり',dict(hp=32,atk=32,spe=2),'マルチスケイル','ゴツゴツメット',['しんそく','じしん','はねやすめ','げきりん']),
 Mon('ギルガルド','いじっぱり',dict(hp=32,atk=32,defn=1,spd=1),'バトルスイッチ','たべのこし',['かげうち','キングシールド','ポルターガイスト','せいなるつるぎ']),
 Mon('キラフロル','おくびょう',dict(hp=2,spa=32,spe=32),'どくげしょう','きあいのタスキ',['パワージェム','ステルスロック','だいちのちから','ヘドロウェーブ']),
 Mon('エースバーン','ようき',dict(hp=2,atk=32,spe=32),'リベロ','きあいのタスキ',['かえんボール','とびひざげり','ダストシュート','ふいうち']),
 Mon('ウルガモス','ずぶとい',{'hp':32,'def':32,'spe':2},'ほのおのからだ','オボンのみ',['ちょうのまい','ほのおのまい','ギガドレイン','あさのひざし']),
]
def main():
    core=TEAM[:4]
    def score(team):
        tot=0; holes=[]
        for r,f in META:
            s=sorted((verdict(m,f) for m in team), reverse=True)
            c=min(1.0,s[0]+ (s[1]*0.5 if len(s)>1 else 0))
            tot+=W.get(r,2)*c
            if s[0]<0.8: holes.append(f.label)
        return tot,holes
    res=[]
    for a,b in itertools.combinations(POOL,2):
        t,h=score(core+[a,b]); res.append((t,a.label,b.label,h))
    res.sort(reverse=True)
    mx=sum(W.get(r,2) for r,_ in META)
    for t,a,b,h in res[:15]: print(f"{t:.1f}/{mx}",a,b,'穴:',h)
    print('current:',score(TEAM))


if __name__ == '__main__':
    main()
