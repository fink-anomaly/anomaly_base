from main import app as fink

from fastapi.testclient import TestClient

user = {'name': 'beta', 'password': 'testpwd'}
user2 = {'username': 'beta', 'password': 'testpwd'}

def test_user_create(client):
        response = client.post('/user/signup', json=user)
        assert response.status_code == 200

token = None

def test_login(client):
        response = client.post('/user/signin', data=user2)
        assert response.status_code == 200, f"{response.status_code=} {response.text=}"

        try:
            j = response.json()
        except:
            j = None
        assert j is not None
        assert 'access_token' in j, f"Need access token in json. Json is {j}"

        global token
        token = j['access_token']

imgid = None
ztfid="ZACASDASDSADtest3"

def test_notification(client):
    with open("test_cutout.png", "rb") as image1, open("test_curve.png", "rb") as image2:
        files = {
            "image1": image1,
            "image2": image2
        }
        data = {
            "description": ( "ID: [N+ZTF18abhehdgtest3](https://api.fink-portal.org/ZTF18abhehdg)"
                             "DR OID (<1''): [437113100007476_test3](https://ztf.snad.space/view/437113100007476)"
                             "GAL coordinates: 39.333665,   -10.333186"
                             "EQU: 294.9632227,   0.907184"
                             "UTC: 2024-05-27 10:03:12.000"
                             "Real bogus: 0.9"
                             "Anomaly score: -0.04"
                           ).replace('\n', '  \n'),
        }
        params = {
            "ztf_id": ztfid
        }
        headers = {
            "Authorization": f"Bearer {token}"
        }
        response = client.post('/images/upload', files=files, params=params, data=data, headers=headers)
        try:
            j = response.json()
        except:
            j = None
        assert j is not None
        assert 'id' in j, f"Image upload should return an image id. Got {j}, for token {token}"
        global imgid
        imgid = j.get("id")

def test_mark_anomaly(client):
    headers = {"Authorization": f"Bearer {token}"}
    response = client.post('/reaction/new', json={"tag":"ANOMALY", "ztf_id":ztfid}, headers=headers)
    assert response.status_code == 200

def test_delete_image(client):
    headers = {"Authorization": f"Bearer {token}"}
    response = client.delete(f'/reaction/{imgid}', headers=headers)
    assert response.status_code == 200
    
def test():
    with TestClient(fink) as client:
        test_user_create(client)
        test_login(client)
        test_notification(client)
        test_mark_anomaly(client)
        test_delete_image(client)
