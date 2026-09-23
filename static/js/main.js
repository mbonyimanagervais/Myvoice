// ==================================
// MyVoice Main JavaScript
// ==================================



document.addEventListener(
    "DOMContentLoaded",
    function(){



        console.log(
            "MyVoice System Loaded"
        );



        const alerts =
        document.querySelectorAll(
            ".alert"
        );



        alerts.forEach(
            function(alert){


                setTimeout(
                    function(){

                        alert.style.display =
                        "none";


                    },
                    5000
                );


            }
        );



    }
);