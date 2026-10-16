import subprocess, os
os.chdir('/home/user/junichi123456.github.io/pokechamp/tool')
cmd=['python3','megapick.py','--all','--depth','3','--seed','h3','--out','hard4','--only','イダイトウ,ムクホーク']
subprocess.run(cmd, stdout=open('/tmp/hard4.log','w'), stderr=subprocess.STDOUT)
subprocess.run('cd /home/user/junichi123456.github.io && git add -A && git commit -qm "6枠目の選定: イダイトウ・ムクホークを苦手4構築で検証(深さ3)\n\nCo-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>\nClaude-Session: https://claude.ai/code/session_017zF5X5Hhgg74J4upn1xuNA" && git pull -q --rebase origin ccr-22f85824-zkfyfy && git push -q -u origin ccr-22f85824-zkfyfy', shell=True)
print('done',flush=True)
