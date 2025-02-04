"""
owtf.api.handlers.auth
~~~~~~~~~~~~~~~~~~~~~~~~

"""
from sqlalchemy.sql.functions import user
from owtf.models.user_login_token import UserLoginToken
from owtf.api.handlers.base import APIRequestHandler
from owtf.lib.exceptions import APIError
from owtf.models.user import User
from datetime import datetime, timedelta
import bcrypt
import json
import jwt
import re
from owtf.settings import (
    JWT_SECRET_KEY,
    JWT_ALGORITHM,
    JWT_EXP_DELTA_SECONDS,
    is_password_valid_regex,
    is_email_valid_regex,
    EMAIL_FROM,
    SMTP_HOST,
    SMTP_LOGIN,
    SMTP_PASS,
    SMTP_PORT,
    SERVER_ADDR,
    SERVER_PORT,
)
from owtf.db.session import Session
from uuid import uuid4
from owtf.models.email_confirmation import EmailConfirmation
from email.mime.text import MIMEText
import smtplib
from email.mime.multipart import MIMEMultipart
import logging
from bs4 import BeautifulSoup
from owtf.utils.logger import OWTFLogger


class LogInHandler(APIRequestHandler):
    """LogIn using the correct credentials (email, password). After successfull login a JWT Token is generated"""

    SUPPORTED_METHODS = ["POST"]

    def post(self):
        """
        **Example request**:

        .. sourcecode:: http

        POST /api/v1/login/ HTTP/1.1
        Content-Type: application/json; charset=UTF-8

        {
            "email": "test@test.com",
            "password": "Test@34335",
        }

        **Example response**:

        .. sourcecode:: http

        **Login successful response**;
        HTTP/1.1 200 OK
        Content-Encoding: gzip
        Vary: Accept-Encoding
        Content-Type: application/json; charset=UTF-8

        {
            "status": "success",
            "data": {
                "jwt-token": "eyJ0eXAiOiJKV1QiLCJhbGciOiJIUzI1NiJ9.eyJ1c2VyX2lkIjozNSwiZXhwIjoxNjIzMjUyMjQwfQ.FjTpJySn3wprlaS26dC9LGBOMrtHJeJsTDJnyCKNmBk"
            }
        }

        **Login failed response**;
        HTTP/1.1 200 OK
        Content-Encoding: gzip
        Vary: Accept-Encoding
        Content-Type: application/json; charset=UTF-8

        {
            "status": "fail",
            "data": "Invalid login credentials"
        }

        """
        email = self.get_argument("email", None)
        password = self.get_argument("password", None)
        if not email:
            err = {"status": "fail", "message": "Missing email value"}
            self.success(err)
        if not password:
            err = {"status": "fail", "message": "Missing password value"}
            self.success(err)
        user = User.find_by_email(self.session, email)
        if (
            user
            and user.password
            and bcrypt.hashpw(password.encode("utf-8"), user.password.encode("utf-8")) == user.password.encode("utf-8")
            and user.is_active
        ):
            payload = {"user_id": user.id, "exp": datetime.utcnow() + timedelta(seconds=JWT_EXP_DELTA_SECONDS)}
            jwt_token = jwt.encode(payload, JWT_SECRET_KEY, JWT_ALGORITHM)
            data = {"jwt-token": jwt_token.decode("utf-8")}
            UserLoginToken.add_user_login_token(self.session, jwt_token, user.id)
            self.success({"status": "success", "message": data})
        elif not user.is_active:
            err = {"status": "fail", "message": "Your account is not active"}
            self.success(err)
        else:
            err = {"status": "fail", "message": "Invalid login credentials"}
            self.success(err)


class RegisterHandler(APIRequestHandler):
    """Registers a new user when he provides email, name, password and confirm password"""

    SUPPORTED_METHODS = ["POST"]

    def post(self):
        """
        **Example request**:

        .. sourcecode:: http

        POST /api/v1/register/ HTTP/1.1
        Content-Type: application/json; charset=UTF-8

        {
            "email": "test@test.com",
            "password": "Test@34335",
            "confirm_password": "Test@34335",
            "name": "test"
        }

        **Example response**:

        .. sourcecode:: http

        **Successful registration response**
        HTTP/1.1 200 OK
        Content-Encoding: gzip
        Vary: Accept-Encoding
        Content-Type: application/json; charset=UTF-8

        {
            "status": "success",
            "data": "User created successfully"
        }

        **Failed registration response**
        HTTP/1.1 200 OK
        Content-Encoding: gzip
        Vary: Accept-Encoding
        Content-Type: application/json; charset=UTF-8

        {
            "status": "fail",
            "data": "Email already exists"
        }

        """
        username = self.get_argument("username", None)
        email = self.get_argument("email", None)
        password = self.get_argument("password", None)
        confirm_password = self.get_argument("confirm_password", None)

        if not username:
            err = {"status": "fail", "message": "Missing username value"}
            self.success(err)
        if not email:
            err = {"status": "fail", "message": "Missing email value"}
            self.success(err)
        if not password:
            err = {"status": "fail", "message": "Missing password value"}
            self.success(err)
        if not confirm_password:
            err = {"status": "fail", "message": "Missing confirm password value"}
            self.success(err)

        already_taken = User.find_by_email(self.session, email)
        match_password = re.search(is_password_valid_regex, password)
        match_email = re.search(is_email_valid_regex, email)

        if password != confirm_password:
            err = {"status": "fail", "message": "Password doesn't match"}
            self.success(err)
        elif not match_email:
            err = {"status": "fail", "message": "Choose a valid email"}
            self.success(err)
        elif not match_password:
            err = {"status": "fail", "message": "Choose a strong password"}
            self.success(err)
        elif already_taken:
            err = {"status": "fail", "message": "Email already exists"}
            self.success(err)
        else:
            hashed_pass = bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt())
            user = {}
            user["email"] = email
            user["password"] = hashed_pass
            user["name"] = username  # need to be chaned to username
            User.add_user(self.session, user)
            data = "User created successfully"
            self.success({"status": "success", "message": data})


class LogOutHandler(APIRequestHandler):
    """Logs out the current user and clears the cookie"""

    def get(self):
        """
        **Example request**:

        .. sourcecode:: http

        GET /api/v1/logout/ HTTP/1.1

        **Example response**:

        .. sourcecode:: http

        HTTP/1.1 200 OK
        Content-Encoding: gzip
        Vary: Accept-Encoding
        Content-Type: application/json; charset=UTF-8

        {
            "status": "success",
            "data": {
                "status": "ok"
            }
        }

        """
        auth = self.request.headers.get("Authorization")
        if auth:
            parts = auth.split()
            token = parts[1]
            session = Session()
            UserLoginToken.delete_user_login_token(session, token)
            data = "Logged out"
            self.success(data)
        else:
            raise APIError(400, "Invalid Token")


class AccountActivationGenerateHandler(APIRequestHandler):
    SUPPORTED_METHODS = ["POST"]

    def post(self):
        email_to = self.get_argument("email", None)
        email_confirmation_dict = {}
        email_confirmation_dict["key_value"] = str(uuid4())
        email_confirmation_dict["expiration_time"] = datetime.now() + timedelta(hours=1)
        user_obj = User.find_by_email(self.session, email_to)
        email_confirmation_dict["user_id"] = user_obj.id
        EmailConfirmation.remove_previous_all(self.session, user_obj.id)
        EmailConfirmation.add_confirm_password(self.session, email_confirmation_dict)

        html = (
            """\
        <html>
        <body>
            Welcome """
            + user_obj.name
            + ", <br/><br/>"
            """ 
            Click here """
            + "http://{}:{}".format(SERVER_ADDR, str(SERVER_PORT))
            + "/email-verify/"
            + email_confirmation_dict["key_value"]
            + """ to activate your account (Link will expire in 1 hour).
        </body>
        </html>
        """
        )
        if SMTP_HOST is not None:
            msg = MIMEMultipart("alternative")
            part = MIMEText(html, "html")
            msg["From"] = EMAIL_FROM
            msg["To"] = email_to
            msg["Subject"] = "Account Activation"
            msg.attach(part)

            with smtplib.SMTP(SMTP_HOST, SMTP_PORT) as server:
                server.login(SMTP_LOGIN, SMTP_PASS)
                server.sendmail(EMAIL_FROM, email_to, msg.as_string())
            del msg
        else:
            logger = OWTFLogger()
            logger.enable_logging()
            logging.info("")
            logging.info("------> Showing the confirmation mail here, Since SMTP server is not set:")
            logger.disable_console_logging()
            html = BeautifulSoup(html, "html.parser").get_text()
            print(html)
        response = {"status": "success", "message": "Email send successful"}
        self.success(response)


class AccountActivationValidateHandler(APIRequestHandler):
    SUPPORTED_METHODS = ["GET"]

    def get(self, key_value):
        email_conf_obj = EmailConfirmation.find_by_key_value(self.session, key_value)
        if email_conf_obj is not None and email_conf_obj.expiration_time >= datetime.now():
            User.activate_user(self.session, email_conf_obj.user_id)
            response = {"status": "success", "message": "Email Verified"}
            self.success(response)
        elif email_conf_obj is not None and email_conf_obj.expiration_time < datetime.now():
            user_id = email_conf_obj.user_id
            user_email = User.find_by_id(self.session, user_id).email
            if user_email is not None:
                response = {"status": "success", "message": "Link Expired", "email": user_email}
                self.success(response)
        else:
            response = {"status": "success", "message": "Invalid Link"}
            self.success(response)
