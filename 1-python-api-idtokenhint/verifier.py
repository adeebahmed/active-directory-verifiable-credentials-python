#!/usr/bin/python

from flask import Flask
from flask import request,Response,redirect
from flask_caching import Cache
from flask.json import jsonify
import json
import logging
import sys, os, tempfile, uuid, time, datetime
import configparser
import argparse
import requests
import jwt, base64
import msal

from __main__ import app
from __main__ import cache
from __main__ import log
from __main__ import config
from __main__ import msalCca

presentationFile = os.getenv('PRESENTATIONFILE')
if presentationFile is None:
    presentationFile = sys.argv[3]
fP = open(presentationFile,)
presentationConfig = json.load(fP)
fP.close()  

apiKey = str(uuid.uuid4())

presentationConfig["callback"]["headers"]["api-key"] = apiKey
presentationConfig["authority"] = config["VerifierAuthority"]
presentationConfig["requestedCredentials"][0]["acceptedIssuers"][0] = config["IssuerAuthority"]

@app.route("/api/verifier/presentation-request", methods = ['GET'])
def presentationRequest():
    """ This method is called from the UI to initiate the presentation of the verifiable credential """
    id = str(uuid.uuid4())
    accessToken = ""
    result = msalCca.acquire_token_for_client( scopes="3db474b9-6a0c-4840-96ac-1fceb342124f/.default" )
    if "access_token" in result:
        print( result['access_token'] )
        accessToken = result['access_token']
    else:
        print(result.get("error") + result.get("error_description"))
    payload = presentationConfig.copy()
    payload["callback"]["url"] = str(request.url_root).replace("http://", "https://") + "api/verifier/presentation-request-callback"
    payload["callback"]["state"] = id
    print( json.dumps(payload) )
    post_headers = { "content-type": "application/json", "Authorization": "Bearer " + accessToken }
    client_api_request_endpoint = config["msIdentityHostName"] + "verifiableCredentials/createPresentationRequest"
    print( client_api_request_endpoint )
    r = requests.post( client_api_request_endpoint
                    , headers=post_headers, data=json.dumps(payload))
    resp = r.json()
    print(resp)
    resp["id"] = id            
    response = Response( json.dumps(resp), status=200, mimetype='application/json')
    response.headers.add('Access-Control-Allow-Origin', '*')
    return response


@app.route("/api/verifier/presentation-request-callback", methods = ['POST'])
def presentationRequestApiCallback():
    """ This method is called by the VC Request API when the user scans a QR code and presents a Verifiable Credential to the service """
    presentationResponse = request.json
    print(presentationResponse)
    if request.headers['api-key'] != apiKey:
        print("api-key wrong or missing")
        return Response( jsonify({'error':'api-key wrong or missing'}), status=401, mimetype='application/json')
    if presentationResponse["requestStatus"] == "request_retrieved":
        cacheData = {
            "status": presentationResponse["requestStatus"],
            "message": "QR Code is scanned. Waiting for validation..."
        }
        cache.set( presentationResponse["state"], json.dumps(cacheData) )
        return ""
    if presentationResponse["requestStatus"] == "presentation_verified":
        print("printing presentationResponse");
        print(presentationResponse);
        cacheData = {
            
            "status": presentationResponse["requestStatus"],
            "message": "Presentation received",
            "payload": presentationResponse["verifiedCredentialsData"],
            "subject": presentationResponse["subject"],
            "firstName": presentationResponse["verifiedCredentialsData"][0]["claims"]["givenName"],
            "lastName": presentationResponse["verifiedCredentialsData"][0]["claims"]["surname"],
            "presentationResponse": presentationResponse
        }
        cache.set( presentationResponse["state"], json.dumps(cacheData) )
        return ""
    return ""

@app.route("/api/verifier/presentation-response", methods = ['GET'])
def presentationRequestStatus():
    """ this function is called from the UI polling for a response from the AAD VC Service.
     when a callback is recieved at the presentationCallback service the session will be updated
     this method will respond with the status so the UI can reflect if the QR code was scanned and with the result of the presentation
     """
    id = request.args.get('id')
    print(id)
    data = cache.get(id)
    print(data)
    if data is not None:
        cacheData = json.loads(data)
        response = Response( json.dumps(cacheData), status=200, mimetype='application/json')
    else:
        response = Response( "", status=200, mimetype='application/json')
    response.headers.add('Access-Control-Allow-Origin', '*')
    return response

@app.route("/api/verifier/presentation-response-b2c", methods = ['POST'])
def presentationResponseB2C():
    presentationResponse = request.json
    id = presentationResponse["id"]
    print(id)
    data = cache.get(id)
    print(data)
    if data is not None:
        cacheData = json.loads(data)
        if cacheData["requestStatus"] == "presentation_verified":
            claims = cacheData["verifiedCredentialsData"][0]["claims"]
            claimsExtra = {
               'vcType': presentationConfig["presentation"]["requestedCredentials"][0]["type"],
               'vcIss': cacheData["presentationResponse"]["requestedCredentials"][0]["issuer"],
               'vcSub': cacheData["presentationResponse"]["subject"],
               'vcKey': cacheData["presentationResponse"]["subject"].replace("did:ion:", "did.ion.").split(":")[0].replace("did.ion.", "did:ion:")
            }
            responseBody = {**claimsExtra, **claims} # merge
            return Response( json.dumps(responseBody), status=200, mimetype='application/json')

    errmsg = {
        'version': '1.0.0', 
        'status': 400,
        'userMessage': 'Verifiable Credentials not presented'
        }
    return Response( json.dumps(errmsg), status=409, mimetype='application/json')
