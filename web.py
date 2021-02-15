from flask import Flask,render_template,Response
from EMonitorDB import EMonitorDB

class CurrentPage(object):
  def __init__(self,action):
    print ("init")
    self.action=action
    #self.response=Response(status=200,headers={})

  def __call__(self, *args):
    print("call")
    # Perform the action
    answer = self.action()
    # Create the answer (bundle it in a correctly formatted HTTP answer)
    self.response = flask.Response(answer, status=200, headers={})
    # Send it
    return self.respons

  def action():
    return render_template('/current.html',data=[[1,2,3]])

class WebServer:
  def __init__ (self):
    self.app_= Flask(__name__)
    self.app_.add_url_rule('/','current',CurrentPage.action)

  def run(self):
    self.app_.run ()




#@app.route('/')
#def current():
#  return render_template('/current.html',data=[[1,2,3]])

if __name__ == '__main__':
    ws=WebServer()
    ws.run()